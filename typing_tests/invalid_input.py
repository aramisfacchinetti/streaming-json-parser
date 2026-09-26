from streaming_json_parser import decode_complete_json


# Pyright must reject a value outside the documented JSON input contract.
decode_complete_json(42)
