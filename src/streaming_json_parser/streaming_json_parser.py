import json
import re
from typing import Any

from src.streaming_json_parser.iterative_state_machine import \
    IterativeStateMachine


class StreamingJsonParser:
    """
    A parser designed to handle potentially incomplete or slightly malformed
    JSON streams, attempting to extract valid JSON objects.
    """
    def __init__(self):
        self.__buffer: str = ""
    
    def consume(self, data: str) -> None:
        """
        Adds new data chunks to the internal buffer after escaping invalid chars.
        """
        # Escape control characters before adding to buffer
        # This helps prevent issues if these chars appear outside strings
        if not self.__is_string(data):
            return

        escaped_data = self.__escape_invalid_control_chars(data)
        if escaped_data:
            self.__buffer += escaped_data

    def get(self) -> dict[str, Any]:
        """
        Attempts to parse and return the first complete JSON object found
        in the buffer. Removes the parsed object (and preceding non-JSON data)
        from the buffer. Returns an empty dict if no complete object is found.
        """
        # --- Initial buffer cleanup ---
        # Remove potential BOM (Byte Order Mark) and leading whitespace
        self.__buffer = self.__buffer.lstrip("\ufeff").lstrip()

        # Find the first opening brace '{' which signifies a potential JSON object start
        start_index = self.__buffer.find("{")
        if start_index == -1:
            # No object start found, clear buffer if it contains only whitespace/junk
            if not self.__buffer.strip():
                 self.__buffer = ""
            # Otherwise, keep buffer as it might be incomplete start of something else
            return {}
        elif start_index > 0:
            # Discard anything before the first '{'
            self.__buffer = self.__buffer[start_index:]

        # If buffer became empty after stripping/finding '{', return empty
        if not self.__buffer:
            return {}

        # --- Attempt 1: Use standard json.raw_decode for well-formed JSON ---
        # This is efficient for standard JSON.
        try:
            decoder = json.JSONDecoder()
            # raw_decode parses one JSON value and returns it and the index where it stopped
            obj, idx = decoder.raw_decode(self.__buffer)

            # Check if the decoded item is a dictionary (object)
            if isinstance(obj, dict):
                # Successfully parsed a standard JSON object
                self.__buffer = self.__buffer[idx:] # Remove parsed part from buffer
                self.__clean_buffer_after_parse() # Clean up potential leading junk
                return obj
            else:
                # Parsed something, but it wasn't an object (e.g., list, primitive)
                # Discard the parsed part and try again (or let partial parser handle it)
                self.__buffer = self.__buffer[idx:]
                # Fall through to the partial parser attempt
        except json.JSONDecodeError:
            # raw_decode failed, likely due to incomplete or malformed JSON.
            # Proceed to the more lenient iterative partial parser.
            pass
        except Exception:
            # Catch other potential errors during raw_decode
            # print(f"Unexpected error during raw_decode: {e}") # Optional logging
            pass # Fall through to partial parser

        # --- Attempt 2: Use the Iterative Partial Parser ---
        # This handles incomplete data, unquoted keys, single quotes etc.
        self.__buffer = self.__buffer.lstrip() # Ensure no leading whitespace

        # Re-check if buffer starts with '{' after potential modification from attempt 1
        if not self.__buffer.startswith('{'):
            start_index = self.__buffer.find("{")
            if start_index == -1:
                 # No '{' found at all anymore
                self.__buffer = ""
                return {}
            else:
                 # Discard leading content if any before '{'
                self.__buffer = self.__buffer[start_index:]

        # Re-check if buffer is empty
        if not self.__buffer:
            return {}

        # Run the iterative state-machine parser
        iterative_state_machine = IterativeStateMachine()
        parsed_obj, consumed_idx = iterative_state_machine.parse_iterative_partial(self.__buffer)

        # Update buffer based on how much was consumed
        if 0 <= consumed_idx <= len(self.__buffer):
            # Successfully parsed or partially parsed, remove consumed part
            self.__buffer = self.__buffer[consumed_idx:]
        else:
            # Indicates an error or unexpected state, clear buffer to be safe
            self.__buffer = ""

        # Clean buffer again after partial parse attempt
        self.__clean_buffer_after_parse()

        # Return the parsed object only if it's a dictionary
        if isinstance(parsed_obj, dict):
            return parsed_obj
        else:
            # The partial parser might return lists or None in some edge cases/errors
            return {}

    def __escape_invalid_control_chars(self, s: str) -> str:
        """
        Escapes control characters (U+0000 to U+001F) that are invalid in JSON
        unless escaped. Standard escapes like \n, \t are preserved.
        """
        # Mapping for standard JSON escapes within the control character range
        escape_map = {
            "\b": "\\b",  # Backspace (U+0008)
            "\f": "\\f",  # Form feed (U+000C)
            "\n": "\\n",  # Line feed (U+000A)
            "\r": "\\r",  # Carriage return (U+000D)
            "\t": "\\t"   # Horizontal tab (U+0009)
        }

        # Replacement function for re.sub
        def replace(match: re.Match[str]) -> str:
            ch = match.group(0)
            # Use standard escape if available, otherwise use \uXXXX format
            return escape_map.get(ch, f"\\u{ord(ch):04x}")

        # Regex to find all characters from U+0000 to U+001F
        return re.sub(r"[\x00-\x1F]", replace, s)

    def __clean_buffer_after_parse(self):
        """
        Helper to clean the buffer after a successful parse.
        Removes leading whitespace and searches for the next potential object start.
        If no '{' is found, clears the buffer if it only contains whitespace.
        """
        self.__buffer = self.__buffer.lstrip()
        next_obj_start = self.__buffer.find("{")

        if next_obj_start > 0:
            # Found another potential object start, discard text before it
            self.__buffer = self.__buffer[next_obj_start:]
        elif next_obj_start == -1:
            # No more '{' found. If buffer is just whitespace, clear it.
            if not self.__buffer.strip():
                self.__buffer = ""
            # Otherwise, keep the buffer content (might be start of next partial object)

    def __is_string(self, data: Any) -> bool:
        """
        Helper to check if the provided data is a string.
        Args:
            data: The data to check.
        Returns:
            True if data is a string, False otherwise.
        """
        return isinstance(data, str)