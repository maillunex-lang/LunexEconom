#!/usr/bin/env bash
set -Eeuo pipefail
mkdir -p emulator-results
APK="$(find emulator-input -maxdepth 2 -name '*.apk' -type f -print -quit)"
test -n "$APK"
PACKAGE="ru.lunex.bashkiriahoneyoil"
cleanup() {
  adb shell screencap -p /sdcard/lunex-smoke.png >/dev/null 2>&1 || true
  adb pull /sdcard/lunex-smoke.png emulator-results/launch.png >/dev/null 2>&1 || true
  adb logcat -d -v time > emulator-results/logcat.txt 2>/dev/null || true
  adb shell dumpsys activity activities > emulator-results/activities.txt 2>/dev/null || true
  adb shell dumpsys window > emulator-results/window.txt 2>/dev/null || true
  adb shell pm list packages | grep -F "$PACKAGE" > emulator-results/installed.txt || true
}
trap cleanup EXIT
adb wait-for-device
adb shell getprop sys.boot_completed | grep -q 1
adb install -r "$APK"
adb shell pm list packages | grep -q "$PACKAGE"
adb logcat -c
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 | tee emulator-results/launch-command.txt
sleep 15
adb shell pidof "$PACKAGE" | tee emulator-results/process.txt
test -s emulator-results/process.txt
adb shell dumpsys activity activities | grep -F "$PACKAGE" > emulator-results/activity-match.txt
test -s emulator-results/activity-match.txt
if adb logcat -d -v brief | grep -E 'FATAL EXCEPTION|Fatal signal' | grep -F "$PACKAGE"; then
  echo 'App fatal error detected' >&2
  exit 1
fi
echo "Emulator smoke passed: package installed, launched and process alive" | tee emulator-results/result.txt
