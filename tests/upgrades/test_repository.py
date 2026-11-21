from codeintent.upgrades import repository


def test_using_scopes_the_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env")
    with repository.using(lambda: "installation"):
        assert repository.token() == "installation"
    assert repository.token() == "env"
