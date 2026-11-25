// The header search box: submits to /search?q=… (the results page reads the query from the URL).
import { useEffect, useState, type FormEvent } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

export const MAX_QUERY = 1000; // the API refuses longer queries (422)

export default function SearchBox() {
  const navigate = useNavigate();
  const onSearch = useLocation().pathname === '/search';
  const [params] = useSearchParams();
  const current = onSearch ? (params.get('q') ?? '') : '';
  const [value, setValue] = useState(current);
  useEffect(() => setValue(current), [current]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = value.trim();
    if (q) navigate(`/search?${new URLSearchParams({ q }).toString()}`);
  };
  return (
    <form className="search-box" role="search" onSubmit={submit}>
      <input type="search" aria-label="Search stories" placeholder="Search" value={value}
        maxLength={MAX_QUERY} onChange={(e) => setValue(e.target.value)} />
    </form>
  );
}
