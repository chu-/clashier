import pytest
from tests.conftest import CONTROLLER_SECRET, GROUP, NODE_A, NODE_B
from tests.support import read_yaml_document, write_yaml_document


@pytest.fixture
def profile_controller(config_dir, local_core):
    controller = local_core()
    core = read_yaml_document(config_dir / "clash-verge.yaml")
    core.update({"external-controller": controller.address, "mode": "rule", "tun": {"enable": False, "mtu": 1400}})
    write_yaml_document(config_dir / "clash-verge.yaml", core)
    document = {"proxies": [{"name": name, "type": "vless", "password": "example-password-not-real"}
                            for name in (NODE_A, NODE_B)],
                "proxy-groups": [{"name": GROUP, "type": "select", "proxies": [NODE_A, NODE_B]}],
                "rules": ["MATCH,DIRECT"]}
    write_yaml_document(config_dir / "profiles/p2.yaml", document)
    return controller


def add_extension(config_dir, uid, kind, contents):
    filename = uid + (".js" if kind == "script" else ".yaml")
    path = config_dir / "profiles" / filename
    if kind == "script":
        path.write_text(contents, encoding="utf-8")
    else:
        write_yaml_document(path, contents)
    catalog = read_yaml_document(config_dir / "profiles.yaml")
    catalog["items"].append({"uid": uid, "name": uid, "type": kind, "file": filename})
    write_yaml_document(config_dir / "profiles.yaml", catalog)


def test_hot_reload_applies_all_extension_layers_and_preserves_host_controls(json_run, config_dir, profile_controller):
    add_extension(config_dir, "ExampleRules", "rules", {
        "prepend": ["DOMAIN,example.com,DIRECT"], "delete": ["MATCH,DIRECT"]})
    add_extension(config_dir, "Merge", "merge", {"dns": {"nameserver": ["192.0.2.53"]},
                                                "profile": {"store-selected": True}})
    add_extension(config_dir, "Script", "script", """
        function main(config, name) {
            console.log(config.secret);
            config.profile.stage = 'global-script';
            config.rules.push('DOMAIN,example.org,DIRECT');
            config.mode = 'direct';
            config['external-controller'] = '127.0.0.1:1';
            return config;
        }
    """)
    add_extension(config_dir, "ExampleMerge", "merge", {"profile": {"stage": "profile-merge"}})
    add_extension(config_dir, "ExampleScript", "script", """
        function main(config) {
            config.profile.observed = config.profile.stage;
            config.profile.stage = 'profile-script';
            config.tun.enable = true;
            return config;
        }
    """)
    catalog = read_yaml_document(config_dir / "profiles.yaml")
    catalog["items"][1]["option"] = {"rules": "ExampleRules", "merge": "ExampleMerge", "script": "ExampleScript"}
    write_yaml_document(config_dir / "profiles.yaml", catalog)
    raw_before = (config_dir / "profiles/p2.yaml").read_bytes()
    result, value = json_run("profile", "activate", "--core-only", "p2")
    assert result.exit_code == 0, result.output
    compiled = profile_controller.reloads[0]
    assert compiled["rules"] == ["DOMAIN,example.com,DIRECT", "DOMAIN,example.org,DIRECT"]
    assert compiled["profile"] == {"store-selected": True, "stage": "profile-script", "observed": "profile-merge"}
    assert compiled["dns"]["nameserver"] == ["192.0.2.53"]
    assert compiled["mode"] == "rule"
    assert compiled["external-controller"] == profile_controller.address
    assert compiled["secret"] == CONTROLLER_SECRET
    assert compiled["tun"] == {"enable": False, "mtu": 1400}
    assert value["data"]["reload"]["status"] == "accepted"
    assert CONTROLLER_SECRET not in result.stdout + result.stderr
    assert (config_dir / "profiles/p2.yaml").read_bytes() == raw_before


@pytest.mark.parametrize("script, code", [
    ("function main(config) { throw new Error(config.secret); }", "SCRIPT_FAILED"),
    ("function main(config) { while (true) {} }", "DEADLINE_EXCEEDED"),
    ("function main(config) { return []; }", "SCRIPT_FAILED"),
])
def test_failed_script_does_not_reload_or_persist(json_run, config_dir, profile_controller, script, code):
    add_extension(config_dir, "Script", "script", script)
    before = (config_dir / "profiles.yaml").read_bytes()
    result, value = json_run("--timeout", "0.2" if code == "DEADLINE_EXCEEDED" else "2",
                            "profile", "activate", "--core-only", "p2")
    assert result.exit_code == 1
    assert value["error"]["code"] == code
    assert not profile_controller.reloads
    assert (config_dir / "profiles.yaml").read_bytes() == before
    assert CONTROLLER_SECRET not in result.stdout + result.stderr


def test_case_sensitive_provider_identities_survive_merging(json_run, config_dir, profile_controller):
    add_extension(config_dir, "Merge", "merge", {
        "proxy-providers": {"ExampleProvider": {"type": "file", "path": "example.yaml"}}})
    add_extension(config_dir, "ExampleMerge", "merge", {"proxy-providers": {"ExampleProvider": {"interval": 60}}})
    catalog = read_yaml_document(config_dir / "profiles.yaml")
    catalog["items"][1]["option"] = {"merge": "ExampleMerge"}
    write_yaml_document(config_dir / "profiles.yaml", catalog)
    result, value = json_run("profile", "activate", "--core-only", "p2")
    assert result.exit_code == 0, result.output
    assert profile_controller.reloads[0]["proxy-providers"] == {
        "ExampleProvider": {"type": "file", "path": "example.yaml", "interval": 60}}
    assert value["data"]["status"] == "verified"
