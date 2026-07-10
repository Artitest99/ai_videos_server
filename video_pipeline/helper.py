def get_array_type(arr):
    if all(isinstance(x, int) for x in arr):
        return "integers"
    elif all(isinstance(x, str) for x in arr):
        return "strings"
    else:
        return "Mixed" 

def to_float(val, default=None):
    try:
        return float(val)
    except Exception:
        if default is not None:
            return float(default)
        raise
