-- Admin sessions opened with a short account password may only change the password.
ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS must_change_password boolean NOT NULL DEFAULT false;
