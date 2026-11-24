import { Route, Routes } from 'react-router-dom';

function Placeholder() {
  return <p className="placeholder">The gazette is being built. Nothing to show yet.</p>;
}

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <h1>Sidereal</h1>
      </header>
      <main>
        <Routes>
          <Route path="*" element={<Placeholder />} />
        </Routes>
      </main>
    </div>
  );
}
