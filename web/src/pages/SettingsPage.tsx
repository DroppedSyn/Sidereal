// Settings (M27, plan §16): focus areas, sources, scoring/budget overrides, notification
// channels, and the effective config (read-only). Everything applies from the next scan.
import { useSettingsView } from '../api/settings';
import FocusAreas from '../components/settings/FocusAreas';
import NotifySettings from '../components/settings/NotifySettings';
import SourceSettings from '../components/settings/SourceSettings';
import TuningForm from '../components/settings/TuningForm';
import { ErrorNote, Loading } from '../components/Status';

export default function SettingsPage() {
  const { data, isPending, isError, error, refetch } = useSettingsView();
  let config;
  if (isPending) config = <Loading what="Loading settings" />;
  else if (isError) config = <ErrorNote error={error} onRetry={() => void refetch()} />;
  else {
    config = (
      <>
        <TuningForm view={data} />
        <NotifySettings channels={data.notify} />
        <section className="settings-section" aria-labelledby="config-title">
          <h3 id="config-title">Effective config (read-only)</h3>
          <details>
            <summary>Show the config file values with overrides applied</summary>
            <pre className="config-dump">{JSON.stringify(data.config, null, 2)}</pre>
          </details>
        </section>
      </>
    );
  }
  return (
    <div className="page settings">
      <header className="page-header">
        <h2 className="page-title">Settings</h2>
      </header>
      <FocusAreas />
      <SourceSettings />
      {config}
    </div>
  );
}
