/**
 * Shown when an authenticated user opens a route their role cannot access.
 */
import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { HiOutlineLockClosed } from 'react-icons/hi2';
import useAuthStore from '../store/authStore';
import { homePathForRole } from '../utils/routeAccess';

export default function AccessDenied() {
  const user = useAuthStore((s) => s.user);
  const location = useLocation();
  const attemptedPath = location.state?.from;
  const homePath = homePathForRole(user?.role);

  return (
    <div className="max-w-7xl mx-auto flex items-center justify-center min-h-[60vh]">
      <div className="text-center card max-w-md">
        <HiOutlineLockClosed className="w-12 h-12 text-red-400 mx-auto mb-4" />
        <h2 className="text-lg font-semibold text-white mb-2">Access Denied</h2>
        <p className="text-slate-400">
          Your account does not have permission to view
          {attemptedPath ? ` ${attemptedPath}` : ' this page'}.
        </p>
        <Link
          to={homePath}
          replace
          className="btn-primary inline-flex items-center justify-center mt-6"
        >
          Back to my dashboard
        </Link>
      </div>
    </div>
  );
}
