import { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { getStoredUser, setStoredUser, setTokens, clearTokens, getToken } from '../api/client';
import { authLogin, authRegister, authMe, authLogout, augurProfile, fetchPersonalizedScores } from '../api/endpoints';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => getStoredUser());
  const [profile, setProfile] = useState(null);
  const [personalScores, setPersonalScores] = useState(null);
  const [loading, setLoading] = useState(false);

  const isAdmin = user?.is_admin === true || user?.is_admin === 1;

  // Load profile + personalized scores after auth
  const loadProfile = useCallback(async () => {
    const [prof, scores] = await Promise.all([
      augurProfile(),
      fetchPersonalizedScores(600),
    ]);
    if (prof) setProfile(prof);
    if (scores) setPersonalScores(scores);
  }, []);

  // On mount, if we have a token, verify + load
  useEffect(() => {
    if (getToken() && user) {
      loadProfile();
    }
  }, []);

  const login = useCallback(async (email, password) => {
    setLoading(true);
    try {
      const data = await authLogin(email, password);
      if (!data || data.error) {
        setLoading(false);
        return { error: data?.error || 'Login failed' };
      }
      setTokens(data.access_token, data.refresh_token);
      const userData = {
        id: data.user_id,
        augur_name: data.augur_name,
        is_admin: data.is_admin,
      };
      setUser(userData);
      setStoredUser(userData);
      await loadProfile();
      setLoading(false);
      return { ok: true, hasProfile: data.has_profile !== false };
    } catch (err) {
      setLoading(false);
      return { error: err.message };
    }
  }, [loadProfile]);

  const register = useCallback(async (email, password, augurName) => {
    setLoading(true);
    try {
      const data = await authRegister(email, password, augurName);
      if (!data || data.error) {
        setLoading(false);
        return { error: data?.error || 'Registration failed' };
      }
      setTokens(data.access_token, data.refresh_token);
      const userData = {
        id: data.user_id,
        augur_name: data.augur_name || augurName,
        is_admin: data.is_admin || false,
      };
      setUser(userData);
      setStoredUser(userData);
      setLoading(false);
      return { ok: true, needsProfile: true };
    } catch (err) {
      setLoading(false);
      return { error: err.message };
    }
  }, []);

  const logout = useCallback(async () => {
    await authLogout();
    clearTokens();
    setUser(null);
    setProfile(null);
    setPersonalScores(null);
  }, []);

  const refreshProfile = useCallback(async () => {
    await loadProfile();
  }, [loadProfile]);

  const value = {
    user,
    profile,
    personalScores,
    isAdmin,
    loading,
    login,
    register,
    logout,
    refreshProfile,
    setProfile,
    setPersonalScores,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
