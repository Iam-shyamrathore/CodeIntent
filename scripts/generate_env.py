"""Create a local environment file without printing or overwriting secrets."""

from pathlib import Path
from secrets import token_hex

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; it was not changed.")
text = (root / ".env.example").read_text()
for key in [
    "POSTGRES_PASSWORD",
    "NEO4J_PASSWORD",
    "CODEINTENT_API_SECRET",
    "CODEINTENT_OPERATOR_TOKEN",
    "CODEINTENT_SESSION_SECRET",
]:
    value = token_hex(32)
    text = text.replace(key + "=\n", key + "=" + value + "\n", 1)
    if key == "POSTGRES_PASSWORD":
        text = text.replace("CHANGE_ME", value)
target.write_text(text)
target.chmod(0o600)
print(
    "Created .env with random local secrets. Add Vertex credentials and your public URL before deployment."
)
