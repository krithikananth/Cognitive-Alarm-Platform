/**
 * Forgot Password — request a reset link by email.
 */
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { motion } from 'framer-motion';
import { HiOutlineClock, HiOutlineEnvelope } from 'react-icons/hi2';
import toast from 'react-hot-toast';
import { authAPI } from '../services/api';

export default function ForgotPassword() {
  const [isLoading, setIsLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const { register, handleSubmit, formState: { errors } } = useForm();

  const onSubmit = async (data) => {
    setIsLoading(true);
    try {
      const { data: res } = await authAPI.forgotPassword({ email: data.email });
      setSent(true);
      toast.success(res.message || 'Check your email for a reset link.');
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(
        typeof detail === 'string' ? detail : 'Unable to send reset email. Try again.'
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen gradient-surface flex items-center justify-center p-4 relative overflow-hidden">
      <div className="absolute top-20 -left-32 w-96 h-96 bg-primary-600/10 rounded-full blur-3xl animate-pulse-slow" />
      <div className="absolute bottom-20 -right-32 w-96 h-96 bg-accent-600/10 rounded-full blur-3xl animate-pulse-slow" />

      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="w-full max-w-md relative z-10"
      >
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl gradient-accent mb-4 shadow-lg shadow-primary-500/20">
            <HiOutlineClock className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white font-display">Forgot Password</h1>
          <p className="text-slate-400 mt-1">We&apos;ll email you a secure reset link</p>
        </div>

        <div className="card">
          {sent ? (
            <div className="space-y-4 text-center">
              <p className="text-slate-300 text-sm leading-relaxed">
                If an account with that email exists, a password reset link has been sent.
                Check your inbox and spam folder.
              </p>
              <Link to="/login" className="btn-primary w-full inline-flex items-center justify-center">
                Back to Sign In
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
              <div>
                <label className="label">Email</label>
                <div className="relative">
                  <HiOutlineEnvelope className="absolute left-3.5 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                  <input
                    type="email"
                    placeholder="you@example.com"
                    className="input pl-11"
                    id="forgot-email"
                    {...register('email', { required: 'Email is required' })}
                  />
                </div>
                {errors.email && (
                  <p className="text-red-400 text-xs mt-1">{errors.email.message}</p>
                )}
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="btn-primary w-full flex items-center justify-center gap-2"
                id="forgot-submit"
              >
                {isLoading ? (
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  'Send Reset Link'
                )}
              </button>
            </form>
          )}
        </div>

        <p className="text-center text-sm text-slate-400 mt-6">
          Remembered your password?{' '}
          <Link to="/login" className="text-primary-400 hover:text-primary-300 font-medium transition">
            Sign in
          </Link>
        </p>
      </motion.div>
    </div>
  );
}
