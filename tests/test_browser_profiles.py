from pathlib import Path

import pytest

from local_agent.mobile.profiles import Profiles


def test_create_update_stale_and_invalid_preserve_bytes(tmp_path):
    profiles = Profiles(tmp_path)
    original = Path("config/browser.yaml").read_text()

    profiles.save("x.yaml", original)

    with pytest.raises(FileExistsError):
        profiles.save("x.yaml", original)

    original_hash = profiles.read("x.yaml")["hash"]
    updated = original + "\n# updated\n"
    profiles.save("x.yaml", updated, expected_hash=original_hash)

    updated_hash = profiles.read("x.yaml")["hash"]
    assert profiles.read("x.yaml")["content"] == updated

    with pytest.raises(FileExistsError):
        profiles.save("x.yaml", original, expected_hash=original_hash)

    assert profiles.read("x.yaml")["content"] == updated
    assert profiles.read("x.yaml")["hash"] == updated_hash

    with pytest.raises(ValueError):
        profiles.save("x.yaml", "[]", expected_hash=updated_hash)

    assert profiles.read("x.yaml")["content"] == updated
    assert profiles.read("x.yaml")["hash"] == updated_hash
