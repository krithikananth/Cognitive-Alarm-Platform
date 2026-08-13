/**
 * Completes Google OAuth. The backend has already set HttpOnly session
 * cookies, so no tokens travel through the URL — this page only loads the
 * current user into the auth store.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { HiOutlineClock } from 'react-icons/hi2';
import toast from 'react-hot-toast';
import useAuthStore from '../store/authStore';

export default function OAuthCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const completeOAuthLogin = useAuthStore((s) => s.completeOAuthLogin);
  const [status, setStatus] = useState('Finishing Google sign-in…');

  useEffect(() => {
    let cancelled = false;

    const finish = async () => {
      if (searchParams.get('error')) {
        toast.error('Google sign-in failed. Please try again.');
        navigate('/login', { replace: true });
        return;
      }

      const result = await completeOAuthLogin();

      if (cancelled) return;

      if (result.success) {
        toast.success('Welcome back!');
        const role = result.user?.role;
        navigate(role === 'admin' ? '/admin' : '/dashboard', { replace: true });
      } else {
        setStatus('Sign-in failed');
        toast.error(result.error || 'Google sign-in failed');
        navigate('/login', { replace: true });
      }
    };

    finish();
    return () => {
      cancelled = true;
    };
  }, [searchParams, completeOAuthLogin, navigate]);

  return (
    <div className="min-h-screen gradient-surface flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center"
      >
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl gradient-accent mb-4 shadow-lg shadow-primary-500/20">
          <HiOutlineClock className="w-8 h-8 text-white" />
        </div>
        <div className="w-8 h-8 border-2 border-white/30 border-t-white rounded-full animate-spin mx-auto mb-4" />
        <p className="text-slate-300">{status}</p>
      </motion.div>
    </div>
  );
}
