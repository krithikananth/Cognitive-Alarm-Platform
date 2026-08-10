/**
 * Shown when an authenticated user opens a route that does not exist.
 */
import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { HiOutlineExclamationTriangle } from 'react-icons/hi2';
import useAuthStore from '../store/authStore';
import { homePathForRole } from '../utils/routeAccess';

export default function NotFound() {
    const user = useAuthStore((s) => s.user);
    const location = useLocation();
    const homePath = homePathForRole(user?.role);

    return (
        <div className="max-w-7xl mx-auto flex items-center justify-center min-h-[60vh]">
            <div className="text-center card max-w-md">
                <HiOutlineExclamationTriangle className="w-12 h-12 text-amber-400 mx-auto mb-4" />
                <p className="text-4xl font-bold text-white mb-1">404</p>
                <h2 className="text-lg font-semibold text-white mb-2">Page Not Found</h2>
                <p className="text-slate-400">
                    We couldn&apos;t find
                    <span className="text-slate-300 break-all"> {location.pathname}</span>. The link may be
                    broken or the page may have moved.
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
