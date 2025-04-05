import json
import re
from typing import Any, Optional, Union

# State constants for the iterative parser
S_INIT, S_OBJ_START, S_OBJ_KEY, S_OBJ_COLON, S_OBJ_VALUE, S_OBJ_COMMA, \
S_ARR_START, S_ARR_VALUE, S_ARR_COMMA, S_COMPLETE, S_ERROR = range(11)

class IterativeStateMachine:
    def __init__(self):
        # Pre-compile regex for finding unquoted keys for efficiency
        # Allows alphanumeric characters, _, -, . as part of the key
        self.__key_pattern = re.compile(r"([a-zA-Z0-9_.-]+)")

    def parse_iterative_partial(self, s: str) -> tuple[Optional[Union[dict[str, Any], list[Any]]], int]:
        """
        An iterative state-machine based parser for potentially incomplete or
        slightly non-standard JSON (unquoted keys, single quotes).
        Attempts to parse one top-level object or array.

        Args:
            s: The string buffer containing JSON data (or partial data).

        Returns:
            A tuple containing:
            - The parsed object (dict) or array (list), or None if parsing fails early.
            - The index in the string 's' up to which parsing consumed input.
              This index might point to the end of a complete structure, or the
              point where parsing stopped due to incomplete data or an error.
        """
        state_stack = [S_INIT]
        # Holds the nested dicts/lists currently being built
        container_stack: list[Union[dict[str, Any], list[Any]]] = []
        # Stores the key for the current object value being parsed
        current_key: Optional[str] = None
        # The root object or list being parsed
        root: Optional[Union[dict[str, Any], list[Any]]] = None
        i = 0 # Current parsing index in string 's'
        len_s = len(s)

        while i < len_s:
            current_state = state_stack[-1]
            char = s[i]

            # Skip Whitespace efficiently
            if char.isspace():
                i += 1
                continue

            try:
                # --- State Machine Logic ---

                # Initial state: Expect start of object '{' or array '['
                if current_state == S_INIT:
                    if char == '{':
                        root = {}
                        container_stack.append(root)
                        state_stack[-1] = S_OBJ_START # Transition to object start state
                        i += 1
                    elif char == '[':
                        root = []
                        container_stack.append(root)
                        state_stack[-1] = S_ARR_START # Transition to array start state
                        i += 1
                    else:
                        # Error: Input doesn't start with '{' or '['
                        state_stack.append(S_ERROR)
                        break # Stop parsing

                # === OBJECT STATES ===

                # Inside object, after '{' or comma: Expect key or '}'
                elif current_state == S_OBJ_START:
                    if char == '}':
                        # Empty object or end of object
                        if not container_stack:
                             # Should be impossible if state logic is correct
                            state_stack.append(S_ERROR)
                            break
                        state_stack.pop() # Pop S_OBJ_START state
                        container_stack.pop() # Pop the completed object
                        i += 1
                        if not state_stack:
                            # If stack is now empty, we finished the root object
                            state_stack.append(S_COMPLETE)
                            break
                        # Otherwise, we were in a nested object, continue parsing parent
                    else:
                        # Expecting an object key next
                        state_stack[-1] = S_OBJ_KEY
                        # Do not increment 'i' here, S_OBJ_KEY needs to process current char

                # Expecting an object key (quoted or unquoted)
                elif current_state == S_OBJ_KEY:
                    key = None
                    start_i = i
                    if char == '"':
                        key, i = self.__parse_partial_string(s, i)
                    elif char == "'": # Non-standard: single quotes
                        key, i = self.__parse_single_quoted_string(s, i)
                    else: # Non-standard: unquoted key
                        key, i = self.__parse_unquoted_key(s, i)

                    # Check if a key was successfully parsed and index advanced
                    if key is not None and i > start_i:
                        current_key = key
                        state_stack[-1] = S_OBJ_COLON # Transition: Expect colon next
                    else:
                        # Failed to parse a valid key at this position
                        state_stack.append(S_ERROR)
                        break # Stop parsing

                # Expecting the colon ':' after an object key
                elif current_state == S_OBJ_COLON:
                    if char == ':':
                        state_stack[-1] = S_OBJ_VALUE # Transition: Expect value next
                        i += 1
                    else:
                        # Error: Missing colon after key
                        state_stack.append(S_ERROR)
                        break # Stop parsing

                # Expecting a value (primitive, object, or array) for the current key
                elif current_state == S_OBJ_VALUE:
                    value_parsed = False
                    start_i = i
                    # Get the object this key-value pair belongs to
                    parent_obj = container_stack[-1]

                    # Basic check for state consistency
                    if not isinstance(parent_obj, dict) or current_key is None:
                        state_stack.append(S_ERROR)
                        break # Should not happen in correct state flow

                    # Check for nested object start
                    if char == '{':
                        new_obj = {}
                        parent_obj[current_key] = new_obj
                        # Transition parent state to expect comma/close brace
                        state_stack[-1] = S_OBJ_COMMA
                        # Push new object and its state onto stacks
                        container_stack.append(new_obj)
                        state_stack.append(S_OBJ_START)
                        i += 1
                        value_parsed = True
                    # Check for nested array start
                    elif char == '[':
                        new_arr = []
                        parent_obj[current_key] = new_arr
                        # Transition parent state to expect comma/close brace
                        state_stack[-1] = S_OBJ_COMMA
                        # Push new array and its state onto stacks
                        container_stack.append(new_arr)
                        state_stack.append(S_ARR_START)
                        i += 1
                        value_parsed = True
                    else:
                        # Attempt to parse a primitive value (string, number, literal)
                         value, next_i = self.__parse_primitive_value(s, i)
                         if next_i > i: # Check if parsing advanced the index
                             parent_obj[current_key] = value
                             state_stack[-1] = S_OBJ_COMMA # Expect comma/close brace next
                             i = next_i # Update index to after the primitive
                             value_parsed = True
                         # else: primitive parsing failed, handled below

                    if not value_parsed:
                        # Error: Could not parse a valid value after the colon
                        state_stack.append(S_ERROR)
                        break # Stop parsing

                # After an object value: Expect comma ',' or closing brace '}'
                elif current_state == S_OBJ_COMMA:
                     if char == ',':
                         state_stack[-1] = S_OBJ_KEY # Transition: Expect another key
                         i += 1
                     elif char == '}':
                         # End of the current object
                         if not container_stack:
                             state_stack.append(S_ERROR) # Error: Unbalanced braces
                             break
                         state_stack.pop() # Pop S_OBJ_COMMA state
                         container_stack.pop() # Pop the completed object
                         i += 1
                         if not state_stack:
                             # Finished the root object
                             state_stack.append(S_COMPLETE)
                             break
                         # Else, continue processing parent container
                     else:
                         # Error: Expected ',' or '}' after value
                         state_stack.append(S_ERROR)
                         break # Stop parsing

                # === ARRAY STATES ===

                # Inside array, after '[' or comma: Expect value or ']'
                elif current_state == S_ARR_START:
                    if char == ']':
                        # Empty array or end of array
                        if not container_stack:
                            state_stack.append(S_ERROR) # Error: Unbalanced brackets
                            break
                        state_stack.pop() # Pop S_ARR_START state
                        container_stack.pop() # Pop the completed array
                        i += 1
                        if not state_stack:
                            # Finished the root array
                            state_stack.append(S_COMPLETE)
                            break
                        # Else, continue processing parent container
                    else:
                        # Expecting an array value next
                        state_stack[-1] = S_ARR_VALUE
                        # Do not increment 'i', S_ARR_VALUE needs to process current char

                # Expecting an array value (primitive, object, or array)
                elif current_state == S_ARR_VALUE:
                    value_parsed = False
                    start_i = i
                    # Get the array this value belongs to
                    parent_arr = container_stack[-1]

                    # Basic check for state consistency
                    if not isinstance(parent_arr, list):
                         state_stack.append(S_ERROR)
                         break # Should not happen

                    # Check for nested object start
                    if char == '{':
                        new_obj = {}
                        parent_arr.append(new_obj)
                        # Transition parent state to expect comma/close bracket
                        state_stack[-1] = S_ARR_COMMA
                        # Push new object and its state
                        container_stack.append(new_obj)
                        state_stack.append(S_OBJ_START)
                        i += 1
                        value_parsed = True
                    # Check for nested array start
                    elif char == '[':
                        new_arr = []
                        parent_arr.append(new_arr)
                        # Transition parent state to expect comma/close bracket
                        state_stack[-1] = S_ARR_COMMA
                        # Push new array and its state
                        container_stack.append(new_arr)
                        state_stack.append(S_ARR_START)
                        i += 1
                        value_parsed = True
                    else:
                        # Attempt to parse a primitive value
                        value, next_i = self.__parse_primitive_value(s, i)
                        if next_i > i: # Check if parsing advanced the index
                            parent_arr.append(value)
                            state_stack[-1] = S_ARR_COMMA # Expect comma/close bracket next
                            i = next_i # Update index
                            value_parsed = True
                        # else: primitive parsing failed, handled below

                    if not value_parsed:
                        # Error: Could not parse a valid value in array
                        state_stack.append(S_ERROR)
                        break # Stop parsing

                # After an array value: Expect comma ',' or closing bracket ']'
                elif current_state == S_ARR_COMMA:
                     if char == ',':
                         state_stack[-1] = S_ARR_VALUE # Transition: Expect another value
                         i += 1
                     elif char == ']':
                         # End of the current array
                         if not container_stack:
                             state_stack.append(S_ERROR) # Error: Unbalanced brackets
                             break
                         state_stack.pop() # Pop S_ARR_COMMA state
                         container_stack.pop() # Pop the completed array
                         i += 1
                         if not state_stack:
                             # Finished the root array
                             state_stack.append(S_COMPLETE)
                             break
                         # Else, continue processing parent container
                     else:
                         # Error: Expected ',' or ']' after array element
                         state_stack.append(S_ERROR)
                         break # Stop parsing

                # === END/ERROR STATES ===

                # Parsing completed successfully for the root element
                elif current_state == S_COMPLETE:
                    break # Exit main loop

                # An error occurred during parsing
                elif current_state == S_ERROR:
                    break # Exit main loop

                # Catchall for unknown states (should not happen)
                else:
                     print(f"Warning: Encountered unknown parser state {current_state}")
                     state_stack.append(S_ERROR)
                     break # Stop parsing

            except IndexError:
                 # Catch errors accessing state_stack or container_stack if they become empty unexpectedly
                 print(f"Error: Stack underflow at index {i}, state {current_state}. Likely malformed JSON.")
                 state_stack.append(S_ERROR)
                 break
            except Exception as inner_ex:
                 # Catch any other unexpected errors during state processing
                 print(f"Error during iterative parse step: {inner_ex} at index {i}, state {current_state}")
                 state_stack.append(S_ERROR)
                 break # Stop parsing on unexpected exceptions

        # Determine the final state and return result
        final_state = state_stack[-1]

        if final_state == S_COMPLETE:
            # Parsed a complete object/array successfully
            return root, i
        elif final_state == S_ERROR:
             # Parsing stopped due to an error. Return whatever was parsed
             # up to the error point (might be None or partial structure)
             # 'i' will be the index where the error occurred.
            return root, i
        else:
            # Loop finished because end of input string 's' was reached,
            # but the JSON structure wasn't 'complete' (e.g., missing closing brace).
            # Return the partially parsed structure and the final index 'i'.
            return root, i
    
    def __parse_primitive_value(self, s: str, i: int) -> tuple[Any, int]:
         """
         Attempts to parse any primitive JSON value (string, number, literal)
         starting at s[i]. Also handles non-standard single quotes.
         Returns the parsed value and the index after it, or (None, i) on failure.
         """
         if i >= len(s):
             # Cannot parse if index is out of bounds
             return None, i

         char = s[i]

         # Check for string start (double quote)
         if char == '"':
             return self.__parse_partial_string(s, i)

         # Check for non-standard string start (single quote)
         if char == "'":
             return self.__parse_single_quoted_string(s, i)

         # Check for number start (digit or minus sign)
         if char in "-0123456789":
             return self.__parse_partial_number(s, i)

         # Check for literals (true, false, null)
         val, next_i = self.__parse_partial_literal(s, i)
         if next_i > i:
             # A literal was successfully parsed
             return val, next_i

         # If none of the above matched, it's not a recognizable primitive start
         return None, i # Indicate failure by returning original index

    def __parse_unquoted_key(self, s: str, i: int) -> tuple[Optional[str], int]:
         """
         Attempts to parse an unquoted object key starting at s[i]. Non-standard.
         Uses the pre-compiled regex `_key_pattern`.
         Returns the key string and the index after it, or (None, i) if no match.
         """
         match = self.__key_pattern.match(s, i)
         if match:
             # Key must not be followed immediately by ":" without whitespace,
             # handle ':' separation in the main loop.
             key = match.group(1)
             return key, match.end()
         else:
             # No match for the unquoted key pattern
             return None, i
    
    def __parse_single_quoted_string(self, s: str, i: int) -> tuple[str, int]:
        """
        Parses a single-quoted string starting at s[i]. Non-standard JSON.
        Assumes s[i] == "'". Handles limited escapes (\' and \\).
        Returns the parsed string content and the index after the closing quote,
        or the end of the string if unterminated.
        """
        i += 1 # skip opening '
        result = []
        escape = False

        while i < len(s):
            ch = s[i]

            if escape:
                if ch == "'":
                    result.append("'")
                elif ch == '\\':
                    result.append('\\')
                else:
                    # Pass through other characters following a backslash
                    result.append('\\')
                    result.append(ch)
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                # End of string found
                return "".join(result), i + 1
            else:
                result.append(ch)

            i += 1

        # Unterminated single-quoted string
        return "".join(result), i

    def __parse_partial_number(self, s: str, i: int) -> tuple[Any, int]:
        """
        Parses a number (int or float) starting at s[i].
        Uses regex for robust matching of JSON number format.
        Returns the parsed number (int or float) and the index after the number,
        or (None, i) if no valid number start is found.
        """
        # Regex for standard JSON numbers (integer and floating point)
        # Allows leading minus, optional fractional part, optional exponent
        num_match = re.match(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?", s[i:])

        if num_match:
            num_str = num_match.group(0)
            end_i = i + len(num_str)
            try:
                # Use json.loads on the matched string for reliable conversion
                # This correctly handles int vs float detection.
                return json.loads(num_str), end_i
            except json.JSONDecodeError:
                # This should theoretically not happen if the regex is correct,
                # but acts as a safeguard. Return the raw string maybe?
                # Or indicate failure. Let's return failure indicator.
                return None, i # Indicate parsing failed despite regex match
        else:
            # No valid number pattern matched at the current position
            return None, i

    def __parse_partial_literal(self, s: str, i: int) -> tuple[Any, int]:
        """
        Parses JSON literals (true, false, null) starting at s[i].
        Checks for word boundaries to avoid partial matches (e.g., 'trueish').
        Returns the literal value (True, False, None) and the index after it,
        or (None, i) if no literal is matched.
        """
        len_s = len(s)

        # Check for 'true'
        if s.startswith("true", i):
            end_i = i + 4
            # Check if it's the end of the string or followed by a non-alphanumeric char
            if end_i == len_s or not s[end_i].isalnum():
                return True, end_i

        # Check for 'false'
        if s.startswith("false", i):
            end_i = i + 5
            # Check for word boundary
            if end_i == len_s or not s[end_i].isalnum():
                return False, end_i

        # Check for 'null'
        if s.startswith("null", i):
            end_i = i + 4
            # Check for word boundary
            if end_i == len_s or not s[end_i].isalnum():
                return None, end_i

        # No literal matched at this position
        return None, i

    def __parse_partial_string(self, s: str, i: int) -> tuple[str, int]:
        """
        Parses a double-quoted string starting at s[i].
        Assumes s[i] == '"'. Handles standard JSON escapes.
        Returns the parsed string content and the index after the closing quote,
        or the end of the string if unterminated.
        """
        i += 1 # skip opening "
        result = []
        escape = False

        while i < len(s):
            ch = s[i]

            # Handle escape sequences
            if escape:
                if ch == 'b':
                    result.append('\b')
                elif ch == 'f':
                    result.append('\f')
                elif ch == 'n':
                    result.append('\n')
                elif ch == 'r':
                    result.append('\r')
                elif ch == 't':
                    result.append('\t')
                elif ch == '"':
                    result.append('"')
                elif ch == '\\':
                    result.append('\\')
                elif ch == '/':
                    result.append('/') # Allowed escape, often seen
                elif ch == 'u':
                    # Unicode escape (basic handling)
                    if i + 4 < len(s):
                        try:
                            hex_code = s[i + 1 : i + 5]
                            result.append(chr(int(hex_code, 16)))
                            i += 4 # Skip hex digits
                        except ValueError:
                            # Invalid hex code, keep the original sequence
                            result.append('\\u')
                            result.append(s[i + 1 : i + 5])
                            i += 4
                    else:
                        # Incomplete escape sequence at end of buffer
                        result.append('\\u')
                        # Append remaining characters if any
                        if i + 1 < len(s):
                            result.append(s[i + 1 :])
                        i = len(s) # Move index to end
                        break # Exit loop as escape is incomplete
                else:
                    # Pass through unknown escape sequences
                    result.append('\\')
                    result.append(ch)
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                # End of string found
                return "".join(result), i + 1
            else:
                # Handle control characters (U+0000 to U+001F)
                # Escape them to \uXXXX format if not already escaped
                if 0x00 <= ord(ch) <= 0x1F:
                    result.append(f'\\u{ord(ch):04x}')
                result.append(ch)

            i += 1

        # If loop finishes without finding closing quote, string is unterminated.
        # Return the partial result found so far.
        return "".join(result), i