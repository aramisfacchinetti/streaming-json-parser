# Streaming JSON Parser

## Objective

This Python module implements a streaming JSON parser designed to process JSON data incrementally. The primary goal is to handle potentially incomplete JSON data streams, such as those produced by Large Language Models (LLMs), and return the current state of the parsed object at any time.

## Requirements Subset

The parser is specifically designed for a subset of JSON where:

- Values consist solely of **strings** and **objects**.
- **Escape sequences** in strings are not expected (though the implementation handles them).
- **Duplicate keys** in objects are not expected (though the implementation may tolerate them, typically keeping the last value).

## Features

- **Incremental Parsing:** Consumes JSON data in chunks via the `consume()` method.
- **Partial State Retrieval:** The `get()` method returns the currently parsed JSON object state, even if the input stream is incomplete.
- **Partial String Values:** Returns partial string values as they are received (e.g., `{"key": "val` is valid partial state).
- **Key Handling:** Keys are only included in the returned object once their value type (string or object start) is identified.
- **Robustness:** Attempts to parse standard JSON efficiently and falls back to a more lenient state-machine parser for incomplete or slightly non-standard input.
- **Non-Standard JSON:** Tolerates some non-standard features like unquoted keys and single-quoted strings.
- **Error Handling:** Attempts to recover from invalid characters or find the first valid JSON object within the buffer.
- **Support for Primitives & Arrays:** Although the requirements focused on strings and objects, the implementation also handles numbers, booleans, null, and arrays as values within objects.

## Implementation Approach

1.  **Buffering:** The `consume()` method appends incoming data chunks to an internal string buffer after escaping potentially invalid control characters.
2.  **Parsing (`get()`):**
    - The buffer is first cleaned by removing leading whitespace and any characters before the first `{`.
    - It attempts parsing using `json.raw_decode` for speed and standard compliance. If a dictionary is successfully decoded, it's returned, and the consumed portion is removed from the buffer.
    - If `raw_decode` fails (due to incomplete data, syntax errors, or non-standard features), it falls back to the `IterativeStateMachine`.
    - The `IterativeStateMachine` parses the buffer character by character, maintaining state to handle nested structures, different value types (including non-standard ones like unquoted keys), and partial inputs.
    - The `get()` method returns the dictionary parsed by either method and updates the buffer, removing the parsed object and any leading garbage before the _next_ potential object. If no complete object can be parsed, an empty dictionary is returned.

## Assumptions and Extensions

The implementation makes the following assumptions or extends the requirements:

1.  **Handling of Additional Primitive Types:** Supports numbers (int, float), booleans (`true`, `false`), and `null` as values, beyond the specified strings and objects.
2.  **Handling of Arrays:** Supports JSON arrays (`[...]`) as values within objects and can parse them, although `get()` only returns top-level _objects_ (`dict`).
3.  **Non-Standard JSON Support:** Tolerates and parses:
    - Unquoted object keys (e.g., `{key: "value"}`).
    - Single-quoted strings (e.g., `{'key': 'value'}`).
4.  **Escape Sequence Handling:** Actively handles standard JSON escape sequences (e.g., `\n`, `\"`) and Unicode escapes (`\uXXXX`) within strings, although they were "not expected".
5.  **Control Character Handling:** Escapes invalid JSON control characters (U+0000 to U+001F) found _outside_ of strings in the input buffer using `\uXXXX` format during `consume`.
6.  **Error Recovery/Robustness:** Discards leading non-JSON data before the first `{` and attempts to parse the first valid object found. Handles multiple objects in the buffer sequentially across `get()` calls.
7.  **Duplicate Keys:** Does not explicitly prevent duplicate keys; standard Python dictionary behavior (last key wins) likely applies.
8.  **Efficiency Strategy:** Uses `json.raw_decode` first, falling back to a custom parser only when necessary.
9.  **Input Type:** `consume` expects string input; other types are ignored.

## Algorithmic Complexity

The efficiency of the `StreamingJsonParser` depends on the method being called and the nature of the input data stream.

- **`consume(buffer: str)`:**

  - **Time Complexity:** Primarily involves appending the new `buffer` (length `k`) to the internal buffer and performing basic character escaping. This is typically **O(k)**. String concatenation in Python can sometimes be O(N+k) where N is the current buffer size, but often optimized closer to O(k) amortized.
  - **Space Complexity:** Increases the internal buffer size by O(k).

- **`get()`:**

  - **Time Complexity:**
    - **Fast Path (`json.raw_decode`):** If the buffer starts with a complete, standard JSON object of size `P`, Python's built-in decoder is used. This is generally efficient, expected to be around **O(P)**.
    - **Fallback Path (`IterativeStateMachine`):** If `raw_decode` fails (due to incomplete data or non-standard syntax), the custom state machine parses the buffer character by character. In the worst case, it might need to scan a significant portion of the buffer (size `B'`). The complexity is dominated by this scan and subsequent buffer slicing, making it roughly **O(B')**.
    - **Overall:** The complexity varies. It's close to O(P) when complete objects are readily available and standard, and approaches O(B') when parsing incomplete or non-standard streams requires the iterative fallback.
  - **Space Complexity:** Does not inherently allocate significant additional space beyond the internal representation of the parsed object being returned. The main space usage comes from the internal buffer managed by `consume`.

- **Overall Space Complexity:** The primary factor is the internal buffer. In the worst case (e.g., a very large stream is consumed without any complete objects being parsed and removed by `get()`), the space complexity can be **O(T)**, where T is the total size of the streamed data received so far. In typical usage where `get()` successfully parses and removes objects, the buffer size stays manageable.

## Usage

```python
# Import the class
from streaming_json_parser import StreamingJsonParser

# Initialize the parser
parser = StreamingJsonParser()

# Consume JSON data chunks
parser.consume('{"name": "Example", "data": {"val') # Partial object value
parser.consume('ue": "stream"}')                  # Complete the object

# Get the current state of the parsed object
# This will return the first complete object found.
current_object = parser.get()
print(current_object)
# Output: {'name': 'Example', 'data': {'value': 'stream'}}

# The buffer is cleared/updated after get(), ready for the next object
parser.consume('{"next": "object"}')
next_object = parser.get()
print(next_object)
# Output: {'next': 'object'}

# Example with partial string value
parser = StreamingJsonParser()
parser.consume('{"key": "partial string')
partial_state = parser.get()
print(partial_state)
# Output: {'key': 'partial string'}

parser.consume(' complete"}')
complete_state = parser.get()
print(complete_state)
# Output: {'key': 'partial string complete'}
```

## Setup

To use this parser and run the tests, you need to install the dependencies:

```bash
pip install -r requirements.txt
```

The `requirements.txt` file includes:

- `pytest`
- `pytest-cov`

## Testing

Unit tests are provided in `test_streaming_json_parser.py`. You can run them using `pytest`:

```bash
pytest
```
