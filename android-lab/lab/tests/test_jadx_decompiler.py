import os
import sys
import shutil
import subprocess
import pytest

def test_jadx_decompiler_on_real_dex(sample_apk, tmp_path):
    """Verifies that JADX decompiles the valid DEX bytecode inside sample_apk into Java source files."""
    lab_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tools_dir = os.path.join(lab_dir, "tools")
    
    jadx_bat = os.path.join(tools_dir, "jadx", "bin", "jadx.bat" if sys.platform == "win32" else "jadx")
    jadx = shutil.which("jadx") or (jadx_bat if os.path.exists(jadx_bat) else None)
    
    if not jadx:
        pytest.skip("JADX binary not found in PATH or lab/tools/jadx")
        
    env = os.environ.copy()
    jdk_dir = os.path.join(tools_dir, "jdk")
    if os.path.isdir(jdk_dir):
        env["JAVA_HOME"] = jdk_dir
        jdk_bin = os.path.join(jdk_dir, "bin")
        if jdk_bin not in env.get("PATH", ""):
            env["PATH"] = jdk_bin + os.pathsep + env.get("PATH", "")

    # Homebrew's jadx wrapper defaults JAVA_HOME to /opt/homebrew/opt/openjdk, which is gone when only
    # a versioned JDK is installed. Without a bundled JDK, hand jadx a JAVA_HOME that exists.
    if not os.path.isdir(jdk_dir):
        home = env.get("JAVA_HOME")
        if not home or not os.path.isdir(home):
            env.pop("JAVA_HOME", None)
            probe = subprocess.run(["/usr/libexec/java_home"], capture_output=True, text=True) if os.path.exists("/usr/libexec/java_home") else None
            found = probe.stdout.strip() if probe and probe.returncode == 0 else ""
            if found and os.path.isdir(found):
                env["JAVA_HOME"] = found
            elif not shutil.which("java", path=env.get("PATH")):
                pytest.skip("No Java runtime for JADX")

    out_dir = str(tmp_path / "jadx_test_out")
    res = subprocess.run([jadx, "-d", out_dir, sample_apk], capture_output=True, text=True, env=env)
    assert res.returncode == 0, f"JADX failed: {res.stderr}\n{res.stdout}"
    
    # Check that decompiled source exists
    main_activity = os.path.join(out_dir, "sources", "com", "testlab", "vulnerable", "MainActivity.java")
    # If package in fixture is com.testlab.fixture:
    fixture_activity = os.path.join(out_dir, "sources", "com", "testlab", "vulnerable", "MainActivity.java")
    assert os.path.exists(fixture_activity), f"Decompiled MainActivity.java not found in {out_dir}"
    with open(fixture_activity, "r", encoding="utf-8") as f:
        content = f.read()
    assert "class MainActivity" in content
