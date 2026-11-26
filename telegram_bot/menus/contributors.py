"""Contributor list for /contributor."""
CONTRIBUTORS = (
    ("vq6oon", "owner and maintainer"),
    ("Krispy Pasta", "developer"),
)

CONTRIBUTORS_CAPTION = "\n".join(
    [
        "Kamui-Bot · v3.0.0",
        "",
        "› Contributors",
        *(f"{name} · {role}" for name, role in CONTRIBUTORS),
        "",
        "@vq6oon",
    ]
)
