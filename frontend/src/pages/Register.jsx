/**
 * Registration page with full user creation form.
 */
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { motion } from 'framer-motion';
import { HiOutlineClock, HiOutlineEnvelope, HiOutlineLockClosed, HiOutlineUser, HiOutlineEye, HiOutlineEyeSlash, HiOutlineGlobeAlt } from 'react-icons/hi2';
import toast from 'react-hot-toast';
import useAuthStore from '../store/authStore';

export default function Register() {
  const [showPassword, setShowPassword] = useState(false);
  const { register: registerUser, isLoading } = useAuthStore();
  const navigate = useNavigate();
  const { register, handleSubmit, formState: { errors }, watch } = useForm();

  const onSubmit = async (data) => {
    const result = await registerUser({
      email: data.email,
      username: data.username,
      password: data.password,
      full_name: data.full_name,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
    if (result.success) {
      toast.success('Account created! Check your email to verify, then log in.');
      navigate('/login');
    } else {
      toast.error(result.error);
    }
  };

  return (
    <div className="min-h-screen gradient-surface flex items-center justify-center p-4 relative overflow-hidden">
      {/* Background */}
      <div className="absolute top-20 -right-32 w-96 h-96 bg-accent-600/10 rounded-full blur-3xl animate-pulse-slow" />
      <div className="absolute bottom-20 -left-32 w-96 h-96 bg-primary-600/10 rounded-full blur-3xl animate-pulse-slow" />

      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="w-full max-w-md relative z-10"
      >
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl gradient-accent mb-4 shadow-lg shadow-accent-500/20">
            <HiOutlineClock className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white font-display">Create Account</h1>
          <p className="text-slate-400 mt-1">Start building better wake-up habits</p>
        </div>

        {/* Register Card */}
        <div className="card">
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            {/* Full Name */}
            <div>
              <label className="label">Full Name</label>
              <div className="relative">
                <HiOutlineUser className="absolute left-3.5 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                <input
                  type="text"
                  placeholder="John Doe"
                  className="input pl-11"
                  id="register-fullname"
                  {...register('full_name')}
                />
              </div>
            </div>

            {/* Username */}
            <div>
              <label className="label">Username</label>
              <div className="relative">
                <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm">@</span>
                <input
                  type="text"
                  placeholder="johndoe"
                  className="input pl-10"
                  id="register-username"
                  {...register('username', {
                    required: 'Username is required',
                    minLength: { value: 3, message: 'At least 3 characters' },
                  })}
                />
              </div>
              {errors.username && <p className="text-red-400 text-xs mt-1">{errors.username.message}</p>}
            </div>

            {/* Email */}
            <div>
              <label className="label">Email</label>
              <div className="relative">
                <HiOutlineEnvelope className="absolute left-3.5 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                <input
                  type="email"
                  placeholder="you@example.com"
                  className="input pl-11"
                  id="register-email"
                  {...register('email', { required: 'Email is required' })}
                />
              </div>
              {errors.email && <p className="text-red-400 text-xs mt-1">{errors.email.message}</p>}
            </div>

            {/* Password */}
            <div>
              <label className="label">Password</label>
              <div className="relative">
                <HiOutlineLockClosed className="absolute left-3.5 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  placeholder="Min. 8 characters"
                  className="input pl-11 pr-11"
                  id="register-password"
                  {...register('password', {
                    required: 'Password is required',
                    minLength: { value: 8, message: 'At least 8 characters' },
                  })}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white transition"
                >
                  {showPassword ? <HiOutlineEyeSlash className="w-5 h-5" /> : <HiOutlineEye className="w-5 h-5" />}
                </button>
              </div>
              {errors.password && <p className="text-red-400 text-xs mt-1">{errors.password.message}</p>}
            </div>

            {/* Timezone auto-detected */}
            <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500/10 border border-primary-500/20">
              <HiOutlineGlobeAlt className="w-4 h-4 text-primary-400 flex-shrink-0" />
              <span className="text-xs text-primary-300">
                Timezone: <strong>{Intl.DateTimeFormat().resolvedOptions().timeZone}</strong>
              </span>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={isLoading}
              className="btn-primary w-full flex items-center justify-center gap-2 mt-2"
              id="register-submit"
            >
              {isLoading ? (
                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                'Create Account'
              )}
            </button>
          </form>
        </div>

        {/* Login Link */}
        <p className="text-center text-sm text-slate-400 mt-6">
          Already have an account?{' '}
          <Link to="/login" className="text-primary-400 hover:text-primary-300 font-medium transition">
            Sign in
          </Link>
          <span className="mx-2 text-slate-600">·</span>
          <Link to="/verify-email" className="text-primary-400 hover:text-primary-300 font-medium transition">
            Verify email
          </Link>
        </p>
      </motion.div>
    </div>
  );
}
