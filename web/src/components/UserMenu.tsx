// Signed-in user and the logout control; nothing when auth is off.
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useLogout, useMe } from '../api/hooks';

export default function UserMenu() {
  const { data: me } = useMe();
  const logout = useLogout();
  const client = useQueryClient();
  const navigate = useNavigate();
  if (me?.auth !== 'on' || !me.username) return null;

  function signOut() {
    logout.mutate(undefined, {
      onSettled: () => {
        client.clear();
        navigate('/login', { replace: true });
      },
    });
  }

  return (
    <div className="user-menu">
      <span className="user-name">{me.username}</span>
      <button type="button" className="link-button" disabled={logout.isPending} onClick={signOut}>
        Log out
      </button>
    </div>
  );
}
