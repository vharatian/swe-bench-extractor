
def is_test(path: str) -> bool:
    p = path.lower()
    return "test/" in p or "tests/" in p or p.endswith("test.java") or p.endswith("it.java")