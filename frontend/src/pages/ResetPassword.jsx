/**
 * Reset Password — set a new password using the email token.
 */
import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { motion } from 'framer-motion';
import { HiOutlineClock, HiOutlineLockClosed, HiOutlineEye, HiOutlineEyeSlash } from 'react-icons/hi2';
import toast from 'react-hot-toast';
import { authAPI } from '../services/api';

export default function ResetPassword() {
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';
  const navigate = useNavigate();
  const { register, handleSubmit, formState: { errors }, watch } = useForm();

  const onSubmit = async (data) => {
    if (!token) {
      toast.error('Reset link is missing or invalid. Request a new one.');
      return;
    }
    setIsLoading(true);
    try {
      const { data: res } = await authAPI.resetPassword({
        token,
        new_password: data.password,
      });
      toast.success(res.message || 'Password updated. Please sign in.');
      navigate('/login');
    } catch (err) {
      const detail = err.response?.data?.detail;
      let message = 'Unable to reset password.';
      if (Array.isArray(detail)) {
        message = detail.map((d) => d.msg).join(', ');
      } else if (typeof detail === 'string') {
        message = detail;
      }
      toast.error(message);
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
          <h1 className="text-2xl font-bold text-white font-display">Reset Password</h1>
          <p className="text-slate-400 mt-1">Choose a new password for your account</p>
        </div>

        <div className="card">
          {!token ? (
            <div className="space-y-4 text-center">
              <p className="text-slate-300 text-sm">
                This reset link is missing or incomplete. Request a new one from the
                forgot password page.
              </p>
              <Link
                to="/forgot-password"
                className="btn-primary w-full inline-flex items-center justify-center"
              >
                Request Reset Link
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
              <div>
                <label className="label">New Password</label>
                <div className="relative">
                  <HiOutlineLockClosed className="absolute left-3.5 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    placeholder="Min. 8 characters"
                    className="input pl-11 pr-11"
                    id="reset-password"
                    {...register('password', {
                      required: 'Password is required',
                      minLength: { value: 8, message: 'At least 8 characters' },
                      validate: {
                        upper: (v) =>
                          /[A-Z]/.test(v) || 'Need at least one uppercase letter',
                        lower: (v) =>
                          /[a-z]/.test(v) || 'Need at least one lowercase letter',
                        digit: (v) => /\d/.test(v) || 'Need at least one digit',
                      },
                    })}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white transition"
                  >
                    {showPassword ? (
                      <HiOutlineEyeSlash className="w-5 h-5" />
                    ) : (
                      <HiOutlineEye className="w-5 h-5" />
                    )}
                  </button>
                </div>
                {errors.password && (
                  <p className="text-red-400 text-xs mt-1">{errors.password.message}</p>
                )}
              </div>

              <div>
                <label className="label">Confirm Password</label>
                <div className="relative">
                  <HiOutlineLockClosed className="absolute left-3.5 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    placeholder="••••••••"
                    className="input pl-11"
                    id="reset-password-confirm"
                    {...register('confirmPassword', {
                      required: 'Please confirm your password',
                      validate: (v) =>
                        v === watch('password') || 'Passwords do not match',
                    })}
                  />
                </div>
                {errors.confirmPassword && (
                  <p className="text-red-400 text-xs mt-1">
                    {errors.confirmPassword.message}
                  </p>
                )}
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="btn-primary w-full flex items-center justify-center gap-2"
                id="reset-submit"
              >
                {isLoading ? (
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  'Update Password'
                )}
              </button>
            </form>
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
