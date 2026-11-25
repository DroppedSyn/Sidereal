// Notification channels (M27/M28): enabled in the config file or not, configured or not (the
// secret itself never reaches the browser), and a "Send test" button per channel.
import { useNotifyTest } from '../../api/settings';
import type { NotifyChannel } from '../../api/types';

function ChannelRow({ channel }: { channel: NotifyChannel }) {
  const test = useNotifyTest();
  const label = channel.name === 'email' ? 'Email' : 'Discord';
  return (
    <li>
      <div className="setting-head">
        <strong>{label}</strong>
        <span className={`badge ${channel.configured ? 'health-ok' : 'health-failing'}`}>
          {channel.configured ? 'configured' : 'not configured'}
        </span>
        <span className="badge">{channel.enabled ? 'on' : 'off'}</span>
        <button type="button" className="action-button" disabled={test.isPending}
          aria-label={`Send test ${label}`} onClick={() => test.mutate(channel.name)}>
          {test.isPending ? 'Sending…' : 'Send test'}
        </button>
      </div>
      {channel.problem ? <p className="settings-note">{channel.problem}</p> : null}
      {test.data ? (
        <p role="status" className={test.data.ok ? 'settings-note' : 'action-error'}>
          {test.data.ok ? 'Test message sent.' : `Test failed: ${test.data.error ?? 'unknown error'}`}
        </p>
      ) : null}
      {test.isError ? <p role="alert" className="action-error">Test failed: {test.error.message}</p> : null}
    </li>
  );
}

export default function NotifySettings({ channels }: { channels: NotifyChannel[] }) {
  return (
    <section className="settings-section" aria-labelledby="notify-title">
      <h3 id="notify-title">Notifications</h3>
      <p className="settings-note">
        Channels are switched on in the config file (<code>[notify] channels</code>); secrets live
        in <code>~/.config/sidereal/env</code> and are never shown here.
      </p>
      <ul className="settings-list">
        {channels.map((c) => <ChannelRow key={c.name} channel={c} />)}
      </ul>
    </section>
  );
}
