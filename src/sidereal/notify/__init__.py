"""Notifications (M28, plan O10, §12.3): new TOP stories by SMTP email and a Discord channel
webhook, once per story and channel, batched per run. Secrets come only from the environment,
systemd credentials or the 0600 env file (``base.load_secrets``)."""
