/**
 * Layout component — sidebar navigation + main content area.
 */
import React, { useState } from 'react';
import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import {
  HiOutlineBell, HiOutlineCog6Tooth, HiOutlineSquares2X2,
  HiOutlineClock, HiOutlineUser, HiOutlineArrowRightOnRectangle,
  HiOutlineBars3, HiOutlineXMark, HiOutlinePuzzlePiece,
  HiOutlineChartBar, HiOutlineTrophy, HiOutlineShieldCheck,
} from 'react-icons/hi2';
import useAuthStore from '../store/authStore';



export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();

  const navItems = user?.role === 'admin'
    ? [
        { to: '/admin', icon: HiOutlineShieldCheck, label: 'Admin Panel' }
      ]
    : [
        { to: '/dashboard', icon: HiOutlineSquares2X2, label: 'Dashboard' },
        { to: '/alarms', icon: HiOutlineClock, label: 'Alarms' },
        { to: '/analytics', icon: HiOutlineChartBar, label: 'Analytics' },
        { to: '/profile', icon: HiOutlineUser, label: 'Profile' },
      ];

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const NavItem = ({ to, icon: Icon, label }) => (
    <NavLink
      to={to}
      onClick={() => setSidebarOpen(false)}
      className={({ isActive }) =>
        `flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
          isActive
            ? 'bg-primary-600/20 text-primary-300 border border-primary-500/30'
            : 'text-slate-400 hover:text-white hover:bg-surface-800/60'
        }`
      }
    >
      <Icon className="w-5 h-5 flex-shrink-0" />
      <span>{label}</span>
    </NavLink>
  );

  return (
    <div className="flex h-screen overflow-hidden gradient-surface">
      {/* ─── Sidebar (Desktop) ─── */}
      <aside className="hidden lg:flex lg:flex-col w-64 glass border-r border-surface-700/50">
        {/* Logo */}
        <div className="flex items-center gap-3 px-6 py-5 border-b border-surface-700/30">
          <div className="w-10 h-10 rounded-xl gradient-accent flex items-center justify-center">
            <HiOutlineClock className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white">ICAP</h1>
            <p className="text-[10px] text-slate-400 uppercase tracking-wider">Cognitive Alarm</p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {navItems.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </nav>

        {/* User Section */}
        <div className="px-3 py-4 border-t border-surface-700/30">
          <div className="flex items-center gap-3 px-3 py-2 mb-2">
            <div className="w-9 h-9 rounded-full gradient-primary flex items-center justify-center text-sm font-bold">
              {user?.full_name?.[0] || user?.username?.[0] || '?'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-white truncate">{user?.full_name || user?.username}</p>
              <p className="text-xs text-slate-400 truncate">{user?.email}</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 w-full px-4 py-2.5 rounded-xl text-sm text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-all duration-200"
          >
            <HiOutlineArrowRightOnRectangle className="w-5 h-5" />
            <span>Logout</span>
          </button>
        </div>
      </aside>

      {/* ─── Mobile Sidebar Overlay ─── */}
      {sidebarOpen && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/60" onClick={() => setSidebarOpen(false)} />
          <aside className="absolute left-0 top-0 bottom-0 w-64 glass animate-slide-in-right">
            <div className="flex items-center justify-between px-6 py-5 border-b border-surface-700/30">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl gradient-accent flex items-center justify-center">
                  <HiOutlineClock className="w-5 h-5 text-white" />
                </div>
                <h1 className="text-sm font-bold">ICAP</h1>
              </div>
              <button onClick={() => setSidebarOpen(false)}>
                <HiOutlineXMark className="w-6 h-6 text-slate-400" />
              </button>
            </div>
            <nav className="px-3 py-4 space-y-1">
              {navItems.map((item) => (
                <NavItem key={item.to} {...item} />
              ))}
            </nav>
          </aside>
        </div>
      )}

      {/* ─── Main Content ─── */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <header className="flex items-center justify-between px-6 py-4 glass border-b border-surface-700/30">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden p-2 rounded-lg hover:bg-surface-800 transition"
          >
            <HiOutlineBars3 className="w-6 h-6 text-slate-300" />
          </button>

          <div className="hidden lg:block" />

          <div className="flex items-center gap-3">
            {user?.role !== 'admin' && (
              <>
                <button onClick={() => navigate('/alarms')} className="p-2.5 rounded-xl hover:bg-surface-800 transition relative">
                  <HiOutlineBell className="w-5 h-5 text-slate-300" />
                  <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-primary-500" />
                </button>
                <button onClick={() => navigate('/profile')} className="p-2.5 rounded-xl hover:bg-surface-800 transition">
                  <HiOutlineCog6Tooth className="w-5 h-5 text-slate-300" />
                </button>
              </>
            )}
          </div>
        </header>

        {/* Page Content */}
        <div className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
