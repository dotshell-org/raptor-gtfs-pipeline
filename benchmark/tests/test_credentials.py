import pytest

from gtfs_bench.credentials import CredentialStore, MissingCredentials


def test_env_file_wins_over_environment(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GRANDLYON_USER=from-file\nGRANDLYON_PASSWORD=file-secret\n", encoding="utf-8")
    store = CredentialStore(env, environ={"GRANDLYON_USER": "from-env", "GRANDLYON_PASSWORD": "env-secret"})
    assert store.get("grandlyon").as_basic_auth() == ("from-file", "file-secret")


def test_environment_fills_what_the_file_leaves_empty(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GRANDLYON_USER=from-file\nGRANDLYON_PASSWORD=\n", encoding="utf-8")
    store = CredentialStore(env, environ={"GRANDLYON_PASSWORD": "env-secret"})
    assert store.get("grandlyon").as_basic_auth() == ("from-file", "env-secret")


def test_missing_credentials_name_the_variables_not_the_values(tmp_path):
    store = CredentialStore(tmp_path / "absent.env", environ={"GRANDLYON_USER": "someone"})
    assert not store.has("grandlyon")
    with pytest.raises(MissingCredentials, match="GRANDLYON_PASSWORD") as error:
        store.get("grandlyon")
    assert "someone" not in str(error.value)


def test_password_never_shows_in_repr(tmp_path):
    store = CredentialStore(None, environ={"X_USER": "u", "X_PASSWORD": "hunter2"})
    assert "hunter2" not in repr(store.get("x"))


def test_prompt_only_when_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "typed-user")
    monkeypatch.setattr("getpass.getpass", lambda prompt: "typed-secret")
    quiet = CredentialStore(None, environ={})
    with pytest.raises(MissingCredentials):
        quiet.get("grandlyon")
    asking = CredentialStore(None, environ={}, interactive=True)
    assert asking.get("grandlyon").as_basic_auth() == ("typed-user", "typed-secret")


def test_set_overrides_lookup():
    store = CredentialStore(None, environ={})
    store.set("grandlyon", "u", "p")
    assert store.has("grandlyon")
    assert store.get("grandlyon").as_basic_auth() == ("u", "p")
