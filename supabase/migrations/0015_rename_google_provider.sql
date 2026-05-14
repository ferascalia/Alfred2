-- Rename provider slug from 'google' to 'google_calendar' to match registry
UPDATE user_integrations SET provider = 'google_calendar' WHERE provider = 'google';
