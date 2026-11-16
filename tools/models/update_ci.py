from pathlib import Path
p=Path(".github/workflows/client-check.yml")
s=p.read_text()
s=s.replace("v2/client-chain-screens]", "v2/client-chain-screens, v2/models-lowpoly]")
s=s.replace("ui1_smoke onboarding_smoke", "ui1_smoke models_load_smoke models_viewer_smoke onboarding_smoke")
marker="      - uses: actions/upload-artifact@v4"
assert marker in s
s=s.replace(marker,'''      - name: Validate 64 low-poly model files and deterministic generation
        run: |
          python3 tools/models/validate_models.py
          python3 -m unittest tools.tests.test_models_pipeline -v
      - name: Model viewer adaptive layout and 10 rendered previews
        run: |
          for i in 0 1 2 3; do
            LUNEX_TEST_SIZE_INDEX="$i" LUNEX_SCREENSHOT_DIR="$GITHUB_WORKSPACE/build/ui-screenshots" \\
              xvfb-run -a ./godot --path client --rendering-driver opengl3 -s tests/models_layout_smoke.gd
          done
'''+marker,1)
p.write_text(s)
print("Client CI models checks integrated")
