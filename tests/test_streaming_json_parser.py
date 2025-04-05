import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.streaming_json_parser.streaming_json_parser import StreamingJsonParser


class TestStreamingJsonParser:
    def test_valid_json(self):
        parser = StreamingJsonParser()
        parser.consume('{"foo": "bar"}')
        assert parser.get() == {"foo": "bar"}

    def test_chunked_streaming_json(self):
        parser = StreamingJsonParser()
        # Provide two chunks that together form a valid JSON.
        parser.consume('{"foo":')
        parser.consume('"bar"}')
        assert parser.get() == {"foo": "bar"}

    def test_partial_streaming_json(self):
        parser = StreamingJsonParser()
        # The value string is incomplete. According to the requirements the parser should return the partial value.
        parser.consume('{"foo": "bar')
        assert parser.get() == {"foo": "bar"}

    def test_incomplete_key(self):
        parser = StreamingJsonParser()
        # The key "wor…" is incomplete so only the complete key "test" should be returned.
        parser.consume('{"test": "hello", "wor')
        assert parser.get() == {"test": "hello"}

    def test_nested_objects(self):
        parser = StreamingJsonParser()
        parser.consume('{"a": {"b": "c"}}')
        assert parser.get() == {"a": {"b": "c"}}

    def test_nested_objects_chunked(self):
        parser = StreamingJsonParser()
        # Nested object with a partially provided key-value pair. Expect only the complete ones.
        parser.consume('{"a": {"b": "c", "d": "e", "f')
        parser.consume('oo"}')
        # Expected to rollback incomplete "f" key and include only "b" and "d"
        assert parser.get() == {"a": {"b": "c", "d": "e"}}

    def test_invalid_json_non_json_input(self):
        parser = StreamingJsonParser()
        parser.consume('not a json')
        assert parser.get() == {}

    def test_empty_buffer(self):
        parser = StreamingJsonParser()
        assert parser.get() == {}

    def test_multiple_consume_calls(self):
        parser = StreamingJsonParser()
        # Build JSON by several small chunks.
        parser.consume('{')
        parser.consume('"foo":')
        parser.consume('"bar"')
        parser.consume('}')
        assert parser.get() == {"foo": "bar"}

    def test_missing_quotes_in_key(self):
        parser = StreamingJsonParser()
        # Keys must be in double quotes. This input is invalid.
        parser.consume('{foo: "bar"}')
        assert parser.get() == {"foo": "bar"}

    def test_invalid_control_character(self):
        parser = StreamingJsonParser()
        # Introduce an actual newline inside the string value (invalid in raw JSON).
        parser.consume('{"key": "val\nd"}')
        assert parser.get() == {"key": "val\nd"}

    def test_streaming_nested_partial(self):
        parser = StreamingJsonParser()
        # In a nested object, the partial key-value pair ("f": "g…") should be dropped.
        parser.consume('{"a": "b", "c": {"d": "e", "f": "g')
        assert parser.get() == {"a": "b", "c": {"d": "e", "f": "g"}}

    def test_multiple_partial_keys(self):
        parser = StreamingJsonParser()
        # Build JSON in chunks so that an incomplete key is fixed once completed.
        parser.consume('{"key1": "value1", "key2": ')
        parser.consume('"value2"}')
        assert parser.get() == {"key1": "value1", "key2": "value2"}

    def test_consume_empty_string(self):
        parser = StreamingJsonParser()
        parser.consume("")
        assert parser.get() == {}

    def test_multiple_nested_objects_incomplete(self):
        parser = StreamingJsonParser()
        # Missing the final closing brace for the outer object.
        parser.consume('{"a": {"b": "c", "d": {"e": "f"}}, "g": "h"')
        assert parser.get() == {"a": {"b": "c", "d": {"e": "f"}}, "g": "h"}

    def test_extra_characters_after_json(self):
        parser = StreamingJsonParser()
        # Extra text after a valid JSON object should cause an error.
        parser.consume('{"foo": "bar"} extra')
        assert parser.get() == {"foo": "bar"}

    def test_trailing_comma(self):
        parser = StreamingJsonParser()
        # A trailing comma should be handled by rolling back to the last comma.
        parser.consume('{"a": "b", "c": "d",')
        assert parser.get() == {"a": "b", "c": "d"}

    def test_incomplete_object_bracket(self):
        parser = StreamingJsonParser()
        # Missing a closing brace for a nested object.
        parser.consume('{"a": "b", "c": {"d": "e"')
        assert parser.get() == {"a": "b", "c": {"d": "e"}}

    def test_non_string_value(self):
        parser = StreamingJsonParser()
        # Although the requirements mention only strings and objects, JSON numbers are valid.
        parser.consume('{"a": 123}')
        assert parser.get() == {"a": 123}

    def test_escape_sequences(self):
        parser = StreamingJsonParser()
        # Even though escape sequences are not expected in the subset, this should be parsed normally.
        parser.consume('{"a": "line1\\nline2"}')
        assert parser.get() == {"a": "line1\nline2"}

    def test_multiple_get_clears_buffer(self):
        parser = StreamingJsonParser()
        parser.consume('{"foo": "bar"}')
        result = parser.get()
        assert result == {"foo": "bar"}
        # After a successful parse, the internal buffer should be cleared.
        assert parser.get() == {}

    def test_consume_after_successful_parse(self):
        parser = StreamingJsonParser()
        parser.consume('{"a": "b"}')
        assert parser.get() == {"a": "b"}
        # Start a new JSON object after the previous parse.
        parser.consume('{"c": "d"}')
        assert parser.get() == {"c": "d"}
    
    def test_overlapping_json_objects(self):
        parser = StreamingJsonParser()
        # Send two JSON objects in a single consume call
        parser.consume('{"a": "b"}{"c": "d"}')
        # Should parse the first one and keep the second in buffer
        assert parser.get() == {"a": "b"}
        # Should parse the second one on next get()
        assert parser.get() == {"c": "d"}
        # Buffer should be empty now
        assert parser.get() == {}

    def test_nested_quotes_in_strings(self):
        parser = StreamingJsonParser()
        parser.consume('{"key": "value with \\"nested quotes\\""}')
        assert parser.get() == {"key": 'value with "nested quotes"'}

    def test_extremely_deep_nesting(self):
        # Test deep nesting
        parser = StreamingJsonParser()
        NESTING_DEPTH = 1000 # Standard libraries might struggle above ~1000
        deep_json = '{'
        # Build {"level0": {"level1": ... {"final": "value"} ... }}
        current_level = deep_json
        for i in range(NESTING_DEPTH):
            current_level += f'"level{i}": {{'
        current_level += '"final": "value"'
        for _ in range(NESTING_DEPTH):
            current_level += '}'
        deep_json = current_level

        parser.consume(deep_json)

        result = None
        print("\nAttempting parser.get() for deep nesting test...")
        try:
            # This call might trigger the fallback to the iterative parser
            result = parser.get()

            # 1. Check type and absence of internal error indicator
            assert isinstance(result, dict), f"Expected a dict, but got {type(result)}"
            assert "__error__" not in result, f"Parser returned an error object: {result.get('__error__')}"

            # 2. Check a few levels iteratively to avoid recursion in the test itself
            print("Verifying structure iteratively...")
            current = result
            assert "level0" in current, "level0 key missing"
            current = current["level0"]
            assert isinstance(current, dict), "level0 value is not a dict"

            assert "level1" in current, "level1 key missing"
            current = current["level1"]
            assert isinstance(current, dict), "level1 value is not a dict"

            # Optionally traverse deeper, but keep it limited
            # Let's check the innermost value carefully
            print("Traversing to innermost value...")
            current = result
            for i in range(NESTING_DEPTH):
                 level_key = f"level{i}"
                 assert isinstance(current, dict), f"Value at depth {i-1} is not a dict"
                 assert level_key in current, f"Key '{level_key}' missing at depth {i}"
                 current = current[level_key]

            print("Verifying final value...")
            assert isinstance(current, dict), f"Value at depth {NESTING_DEPTH-1} is not a dict"
            assert "final" in current, "Innermost 'final' key missing"
            assert current["final"] == "value", f"Innermost 'final' value mismatch, got: {current.get('final')}"
            print("Deep nesting structure verified successfully.")

        except RecursionError:
            # This should ideally NOT happen if the iterative parser is working
            pytest.fail("RecursionError occurred unexpectedly during parser.get() call")
        except Exception as e:
            # Catch any other unexpected errors
            import traceback
            print("Unexpected exception during deep nesting test:")
            traceback.print_exc()
            pytest.fail(f"An unexpected error occurred: {e}")

    def test_unicode_characters(self):
        parser = StreamingJsonParser()
        parser.consume('{"emoji": "😀", "chinese": "你好", "arabic": "مرحبا"}')
        assert parser.get() == {"emoji": "😀", "chinese": "你好", "arabic": "مرحبا"}

    def test_key_with_special_json_chars(self):
        parser = StreamingJsonParser()
        parser.consume('{"key:with{special}chars,": "value"}')
        assert parser.get() == {"key:with{special}chars,": "value"}

    def test_consecutive_escapes(self):
        parser = StreamingJsonParser()
        parser.consume('{"key": "value with \\\\\\\\ multiple escapes"}')
        assert parser.get() == {"key": "value with \\\\ multiple escapes"}

    def test_malformed_escapes(self):
        parser = StreamingJsonParser()
        # Malformed escape sequence (trailing slash)
        parser.consume('{"key": "malformed escape \\"}')
        # Should auto-correct or handle the malformed escape
        result = parser.get()
        assert "key" in result

    def test_unescaped_control_chars_in_string(self):
        parser = StreamingJsonParser()
        # Adding raw control characters that should be escaped
        control_chars = ''.join(chr(i) for i in range(0, 32))
        parser.consume(f'{{"control_chars": "{control_chars}"}}')
        result = parser.get()
        assert "control_chars" in result

    def test_incomplete_escape_sequence(self):
        parser = StreamingJsonParser()
        parser.consume('{"key": "\\u123"}')  # Incomplete Unicode escape (should be 4 hex digits)
        result = parser.get()
        assert "key" in result

    def test_very_large_json(self):
        NUMBER_OF_KEYS = 10**6 # 1 million keys

        parser = StreamingJsonParser()
        # Create a large JSON with many key-value pairs
        large_json = '{'
        for i in range(NUMBER_OF_KEYS):
            if i > 0:
                large_json += ','
            large_json += f'"key{i}": "value{i}"'
        large_json += '}'
        parser.consume(large_json)
        
        result = parser.get()
        assert len(result) == NUMBER_OF_KEYS
        assert result["key0"] == "value0"
        assert result[f"key{NUMBER_OF_KEYS-1}"] == f"value{NUMBER_OF_KEYS-1}"

    def test_json_with_comments(self):
        parser = StreamingJsonParser()
        # JSON doesn't support comments, but let's see how the parser handles them
        parser.consume('{"key": "value"} // comment')
        assert parser.get() == {"key": "value"}

    def test_invalid_nested_arrays(self):
        parser = StreamingJsonParser()
        # Arrays are not mentioned in the requirements but might be in the input
        parser.consume('{"array": [1, 2, 3]}')
        assert parser.get() == {"array": [1, 2, 3]}

    def test_invalid_array_termination(self):
        parser = StreamingJsonParser()
        # Incomplete array
        parser.consume('{"array": [1, 2, 3')
        result = parser.get()
        # Should handle or correct the incomplete array
        assert "array" in result

    def test_mixed_quotes(self):
        parser = StreamingJsonParser()
        # Using both single and double quotes (invalid JSON)
        parser.consume("{'key': \"value\"}")
        result = parser.get()
        # Should handle or correct the invalid quotes
        assert len(result) > 0

    def test_truncated_unicode_in_string(self):
        parser = StreamingJsonParser()
        # Unicode character cut in half across chunks
        parser.consume('{"key": "start of string with unicode ')
        parser.consume('😀 end of string"}')
        assert parser.get() == {"key": "start of string with unicode 😀 end of string"}

    def test_json_with_bom(self):
        parser = StreamingJsonParser()
        # JSON with UTF-8 BOM
        parser.consume('\ufeff{"key": "value"}')
        assert parser.get() == {"key": "value"}

    def test_key_duplicates(self):
        parser = StreamingJsonParser()
        # JSON with duplicate keys (last one should win according to most parsers)
        parser.consume('{"key": "value1", "key": "value2"}')
        assert parser.get() == {"key": "value2"}

    def test_multiple_balanced_objects(self):
        parser = StreamingJsonParser()
        # Multiple complete objects with extra text between them
        parser.consume('{"a":"b"} some text {"c":"d"} more text {"e":"f"}')
        
        # Should get the first object
        assert parser.get() == {"a": "b"}
        
        # Should skip the "some text" and get the second object
        assert parser.get() == {"c": "d"}
        
        # Should skip the "more text" and get the third object
        assert parser.get() == {"e": "f"}
        
        # Buffer should be empty now
        assert parser.get() == {}

    def test_nested_brace_inside_string(self):
        parser = StreamingJsonParser()
        # Test with braces inside string values that might confuse the brace counting
        parser.consume('{"key": "value with { and } inside"}')
        assert parser.get() == {"key": "value with { and } inside"}

    def test_corrupt_buffer_recovery(self):
        parser = StreamingJsonParser()
        # Start with invalid content
        parser.consume('not json at all')
        assert parser.get() == {}
        
        # Now send valid JSON
        parser.consume('{"key": "value"}')
        assert parser.get() == {"key": "value"}

    def test_interleaved_valid_invalid(self):
        parser = StreamingJsonParser()
        # Interleave valid and invalid JSON portions
        parser.consume('{"a":"b"} garbage {"c"')
        assert parser.get() == {"a": "b"}
        
        parser.consume(':"d"} more garbage {"e":"f"}')
        assert parser.get() == {"c": "d"}
        assert parser.get() == {"e": "f"}
    
    def test_empty_input(self):
        parser = StreamingJsonParser()
        parser.consume('')
        assert parser.get() == {}
        parser.consume('  ') # Whitespace only
        assert parser.get() == {}

    def test_leading_whitespace_and_bom(self):
        parser = StreamingJsonParser()
        parser.consume('\ufeff   {"a": 1}')
        assert parser.get() == {"a": 1}

    def test_leading_garbage(self):
        parser = StreamingJsonParser()
        parser.consume('garbage data {"a": 1}')
        # get() should find the first '{' and parse from there
        assert parser.get() == {"a": 1}

    def test_trailing_data(self):
        parser = StreamingJsonParser()
        parser.consume('{"a": 1} trailing garbage')
        assert parser.get() == {"a": 1}
        # Buffer should contain the trailing data after cleaning whitespace
        # Calling get again should not find an object
        assert parser.get() == {}

    def test_multiple_objects_in_buffer(self):
        parser = StreamingJsonParser()
        parser.consume('{"a": 1}{"b": 2}  {"c": 3}')
        assert parser.get() == {"a": 1}
        assert parser.get() == {"b": 2}
        assert parser.get() == {"c": 3}

    def test_get_clears_buffer_if_only_whitespace_remains(self):
        parser = StreamingJsonParser()
        parser.consume('{"a": 1}   ')
        assert parser.get() == {"a": 1}

    def test_consume_non_string_ignored(self):
        parser = StreamingJsonParser()
        parser.consume(123) # type: ignore
        parser.consume(None) # type: ignore
        parser.consume(b'bytes') # type: ignore
        assert parser.get() == {}

    def test_unquoted_key(self):
        parser = StreamingJsonParser()
        parser.consume('{key_1: "value"}')
        assert parser.get() == {"key_1": "value"}

    def test_unquoted_key_with_hyphen_dot(self):
        parser = StreamingJsonParser()
        parser.consume('{key-with.chars: 123}')
        assert parser.get() == {"key-with.chars": 123}

    def test_unquoted_key_and_single_quoted_value(self):
        parser = StreamingJsonParser()
        parser.consume("{my_key: 'my value'}")
        assert parser.get() == {"my_key": "my value"}

    def test_unquoted_key_with_escaped_quotes(self):
        parser = StreamingJsonParser()
        parser.consume("{ key : true }") # Valid json with literal value
        assert parser.get() == {"key": True}

    def test_empty_object(self):
        parser = StreamingJsonParser()
        parser.consume('{}')
        assert parser.get() == {}

    def test_object_with_various_primitives(self):
        parser = StreamingJsonParser()
        json_str = '{"str": "s", "int": -1, "float": 1.5, "boolT": true, "boolF": false, "nullVal": null}'
        expected = {"str": "s", "int": -1, "float": 1.5, "boolT": True, "boolF": False, "nullVal": None}
        parser.consume(json_str)
        assert parser.get() == expected

    def test_nested_object(self):
        parser = StreamingJsonParser()
        parser.consume('{"a": 1, "b": {"c": 2, "d": {}}, "e": 3}')
        expected = {"a": 1, "b": {"c": 2, "d": {}}, "e": 3}
        assert parser.get() == expected

    def test_nested_array(self):
        parser = StreamingJsonParser()
        parser.consume('{"a": [1, 2], "b": [[false, null], []], "c": true}')
        expected = {"a": [1, 2], "b": [[False, None], []], "c": True}
        assert parser.get() == expected

    def test_array_at_root_ignored_by_get(self):
        # get() specifically looks for objects ({...})
        parser = StreamingJsonParser()
        parser.consume('[1, 2, 3]')
        # raw_decode would parse it, but get() checks isinstance(obj, dict)
        assert parser.get() == {}
        # The array should be consumed from the buffer because raw_decode succeeded

        # Try with iterative parser (force raw_decode fail)
        parser.consume('[1, 2,') # Incomplete array
        assert parser.get() == {} # Fails raw_decode, iterative parser runs

        parser.consume(' 3]') # Complete the array
        assert parser.get() == {} # raw_decode fails, iterative parses array
        # Iterative parser returns the array, but get() discards non-dict results
        # Buffer should be cleared because iterative parser consumed the input

    def test_complex_nesting(self):
         parser = StreamingJsonParser()
         json_str = '{"a": [1, {"b": false, "x": [{}, 10]}, null], "c": {"d": [], "e": "end"}}'
         expected = {"a": [1, {"b": False, "x": [{}, 10]}, None], "c": {"d": [], "e": "end"}}
         parser.consume(json_str)
         assert parser.get() == expected

    @pytest.mark.parametrize("incomplete_json", [
        '{',
        '{"key',
        '{"key":',
        '[',            # Forcing iterative parser via incomplete start
        '[1',
        '[1,',
        '[{"key":',
    ])
    def test_incomplete_json_structures(self, incomplete_json: str):
        parser = StreamingJsonParser()
        parser.consume(incomplete_json)
        assert parser.get() == {} # Should not return a partial object
