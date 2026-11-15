package org.lunex.update;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import android.provider.Settings;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.core.content.FileProvider;

import org.godotengine.godot.Godot;
import org.godotengine.godot.plugin.GodotPlugin;
import org.godotengine.godot.plugin.UsedByGodot;

import java.io.File;
import java.io.FileInputStream;
import java.io.OutputStream;

public final class LunexInstaller extends GodotPlugin {
    private static final String TAG = "LunexInstaller";

    public LunexInstaller(Godot godot) {
        super(godot);
    }

    @NonNull @Override
    public String getPluginName() {
        return "LunexInstaller";
    }

    @UsedByGodot
    public boolean isWifiConnected() {
        Activity activity = getActivity();
        if (activity == null) return false;
        ConnectivityManager manager = (ConnectivityManager) activity.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (manager == null || manager.getActiveNetwork() == null) return false;
        NetworkCapabilities capabilities = manager.getNetworkCapabilities(manager.getActiveNetwork());
        return capabilities != null && capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI);
    }

    private SecretKey tokenKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        SecretKey key = (SecretKey) store.getKey("lunex_v2_auth", null);
        if (key != null) return key;
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder("lunex_v2_auth",
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).build());
        return generator.generateKey();
    }

    @UsedByGodot
    public boolean saveToken(String token) {
        Activity activity = getActivity();
        if (activity == null) return false;
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, tokenKey());
            byte[] ciphertext = cipher.doFinal(token.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            String data = Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP) + ":" +
                          Base64.encodeToString(ciphertext, Base64.NO_WRAP);
            return activity.getSharedPreferences("lunex_private_auth", Context.MODE_PRIVATE)
                    .edit().putString("access", data).commit();
        } catch (Exception e) {
            Log.e(TAG, "Protected token storage failed", e);
            return false;
        }
    }

    @UsedByGodot
    public String loadToken() {
        Activity activity = getActivity();
        if (activity == null) return "";
        try {
            String stored = activity.getSharedPreferences("lunex_private_auth", Context.MODE_PRIVATE)
                    .getString("access", "");
            if (stored.isEmpty()) return "";
            String[] values = stored.split(":", -1);
            if (values.length != 2) return "";
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            byte[] iv = Base64.decode(values[0], Base64.NO_WRAP);
            cipher.init(Cipher.DECRYPT_MODE, tokenKey(), new GCMParameterSpec(128, iv));
            return new String(cipher.doFinal(Base64.decode(values[1], Base64.NO_WRAP)), java.nio.charset.StandardCharsets.UTF_8);
        } catch (Exception e) {
            Log.e(TAG, "Protected token restore failed", e);
            return "";
        }
    }

    @UsedByGodot
    public void clearToken() {
        Activity activity = getActivity();
        if (activity != null) {
            activity.getSharedPreferences("lunex_private_auth", Context.MODE_PRIVATE).edit().remove("access").apply();
        }
    }

    @UsedByGodot
    public void installApk(String path) {
        Activity activity = getActivity();
        if (activity == null) return;
        activity.runOnUiThread(() -> install(activity, path));
    }

    private void install(Activity activity, String path) {
        File apk = new File(path);
        try {
            File files = activity.getFilesDir().getCanonicalFile();
            File canonical = apk.getCanonicalFile();
            if (!canonical.getPath().startsWith(files.getPath() + File.separator) ||
                    !canonical.getName().equals("lunex.apk") || !canonical.isFile() || canonical.length() == 0) {
                Log.e(TAG, "Rejected an APK path outside the application's private data");
                return;
            }
            if (Build.VERSION.SDK_INT >= 26 && !activity.getPackageManager().canRequestPackageInstalls()) {
                Intent settings = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + activity.getPackageName()));
                activity.startActivity(settings);
                return; // User must grant permission and tap Install again.
            }

            PackageInstaller installer = activity.getPackageManager().getPackageInstaller();
            PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            params.setAppPackageName(activity.getPackageName());
            params.setSize(canonical.length());
            if (Build.VERSION.SDK_INT >= 31) {
                // Android only honours this when the app meets installer-of-record and permission requirements.
                params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED);
            }
            int id = installer.createSession(params);
            try (PackageInstaller.Session session = installer.openSession(id)) {
                try (FileInputStream input = new FileInputStream(canonical);
                     OutputStream output = session.openWrite("base.apk", 0, canonical.length())) {
                    byte[] buffer = new byte[64 * 1024];
                    int count;
                    while ((count = input.read(buffer)) >= 0) {
                        if (count != 0) output.write(buffer, 0, count);
                    }
                    session.fsync(output);
                }
                Intent status = new Intent(activity, InstallStatusReceiver.class);
                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= 31) flags |= PendingIntent.FLAG_MUTABLE;
                PendingIntent pending = PendingIntent.getBroadcast(activity, id, status, flags);
                session.commit(pending.getIntentSender());
            }
        } catch (Exception e) {
            Log.e(TAG, "PackageInstaller failure; trying user-confirmed FileProvider", e);
            try {
                Uri uri = FileProvider.getUriForFile(activity, activity.getPackageName() + ".fileprovider", apk);
                Intent view = new Intent(Intent.ACTION_VIEW);
                view.setDataAndType(uri, "application/vnd.android.package-archive");
                view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                activity.startActivity(view);
            } catch (Exception fallbackError) {
                Log.e(TAG, "User-confirmed fallback failed", fallbackError);
            }
        }
    }
}
