/**
 * Email Verification — confirm address via token, or resend the link.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { motion } from 'framer-motion';
import { HiOutlineClock, HiOutlineEnvelope, HiOutlineCheckCircle, HiOutlineXCircle } from 'react-icons/hi2';
import toast from 'react-hot-toast';
import { authAPI } from '../services/api';

export default function VerifyEmail() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';
  const [status, setStatus] = useState(token ? 'verifying' : 'idle');
  const [message, setMessage] = useState('');
  const [isResending, setIsResending] = useState(false);
  const attempted = useRef(false);
  const { register, handleSubmit, formState: { errors } } = useForm();

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true;

    const verify = async () => {
      try {
        const { data } = await authAPI.verifyEmail({ token });
        setStatus('success');
        setMessage(data.message || 'Email verified successfully.');
        toast.success(data.message || 'Email verified!');
      } catch (err) {
        const detail = err.response?.data?.detail;
        const msg =
          typeof detail === 'string'
            ? detail
            : 'Invalid or expired verification link.';
        setStatus('error');
        setMessage(msg);
        toast.error(msg);
      }
    };

    verify();
  }, [token]);

  const onResend = async (data) => {
    setIsResending(true);
    try {
      const { data: res } = await authAPI.resendVerification({ email: data.email });
      toast.success(res.message || 'Verification email sent.');
      setStatus('resent');
      setMessage(res.message);
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(
        typeof detail === 'string' ? detail : 'Unable to resend verification email.'
      );
    } finally {
      setIsResending(false);
    }
  };

  return (
    <div className="min-h-screen gradient-surface flex items-center justify-center p-4 relative overflow-hidden">
      <div className="absolute top-20 -right-32 w-96 h-96 bg-accent-600/10 rounded-full blur-3xl animate-pulse-slow" />
      <div className="absolute bottom-20 -left-32 w-96 h-96 bg-primary-600/10 rounded-full blur-3xl animate-pulse-slow" />

      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="w-full max-w-md relative z-10"
      >
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl gradient-accent mb-4 shadow-lg shadow-accent-500/20">
            <HiOutlineClock className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white font-display">Email Verification</h1>
          <p className="text-slate-400 mt-1">Confirm your account email address</p>
        </div>

        <div className="card space-y-5">
          {status === 'verifying' && (
            <div className="flex flex-col items-center gap-3 py-4">
              <div className="w-8 h-8 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <p className="text-slate-300 text-sm">Verifying your email…</p>
            </div>
          )}

          {status === 'success' && (
            <div className="flex flex-col items-center gap-3 text-center py-2">
              <HiOutlineCheckCircle className="w-12 h-12 text-emerald-400" />
              <p className="text-slate-200 text-sm">{message}</p>
              <Link to="/login" className="btn-primary w-full inline-flex items-center justify-center mt-2">
                Continue to Sign In
              </Link>
            </div>
          )}

          {(status === 'error' || status === 'idle' || status === 'resent') && (
            <>
              {status === 'error' && (
                <div className="flex flex-col items-center gap-2 text-center">
                  <HiOutlineXCircle className="w-10 h-10 text-red-400" />
                  <p className="text-slate-300 text-sm">{message}</p>
                </div>
              )}

              {status === 'resent' && (
                <p className="text-slate-300 text-sm text-center">{message}</p>
              )}

              {status === 'idle' && (
                <p className="text-slate-300 text-sm text-center">
                  Enter your email to receive a new verification link.
                </p>
              )}

              <form onSubmit={handleSubmit(onResend)} className="space-y-4">
                <div>
                  <label className="label">Email</label>
                  <div className="relative">
                    <HiOutlineEnvelope className="absolute left-3.5 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                    <input
                      type="email"
                      placeholder="you@example.com"
                      className="input pl-11"
                      id="verify-resend-email"
                      {...register('email', { required: 'Email is required' })}
                    />
                  </div>
                  {errors.email && (
                    <p className="text-red-400 text-xs mt-1">{errors.email.message}</p>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={isResending}
                  className="btn-primary w-full flex items-center justify-center gap-2"
                  id="verify-resend-submit"
                >
                  {isResending ? (
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : (
                    'Resend Verification Email'
                  )}
                </button>
              </form>
            </>
          )}
        </div>

        <p className="text-center text-sm text-slate-400 mt-6">
          <Link to="/login" className="text-primary-400 hover:text-primary-300 font-medium transition">
            Back to Sign In
          </Link>
        </p>
      </motion.div>
    </div>
  );
}
