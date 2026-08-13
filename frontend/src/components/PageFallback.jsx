/**
 * Fallback shown while a lazily-loaded route chunk is downloading.
 *
 * Deliberately dependency-free (no framer-motion, no icons): it ships in the
 * initial bundle, so anything it imports would be pulled out of the very chunks
 * that route splitting is meant to defer.
 */
import React from 'react';

function PageFallback({ label = 'Loading…' }) {
  return (
    <div
      className="flex items-center justify-center py-24"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="w-10 h-10 border-4 border-accent-500 border-t-transparent rounded-full animate-spin" />
      <span className="sr-only">{label}</span>
    </div>
  );
}

export default PageFallback;
