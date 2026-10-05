"""Analyze a working tree or commit range without running tests."""
import json
import sys
from change_impact import arguments, human, plan

if __name__ == "__main__":
    args = arguments(__doc__).parse_args()
    try:
        result = plan(args)
        print(json.dumps(result, indent=2) if args.json else human(result))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Impact analysis failed: {error}", file=sys.stderr)
        sys.exit(1)
