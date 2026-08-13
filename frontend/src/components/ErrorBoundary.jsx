/**
 * React error boundary.
 *
 * A render-time exception anywhere below unmounts the whole React tree, so
 * before this existed a single bad value produced a blank white page with no
 * recovery and — because nothing was reported — no way for anyone operating the
 * platform to know it had happened.
 *
 * The boundary keeps the failure local, shows a recoverable fallback, and sends
 * the error (with its component stack and the correlation id of the last API
 * call) to the backend log.
 */
import React from 'react';
import { HiOutlineExclamationTriangle, HiArrowPath } from 'react-icons/hi2';
import { reportClientError } from '../services/errorReporting';

class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { error: null, reportedRequestId: null };
        this.handleRetry = this.handleRetry.bind(this);
        this.handleReload = this.handleReload.bind(this);
    }

    static getDerivedStateFromError(error) {
        return { error };
    }

    componentDidCatch(error, info) {
        const report = reportClientError(error, {
            source: 'error_boundary',
            componentStack: info?.componentStack,
            boundary: this.props.name || 'unnamed',
        });
        // Suppressed reports (duplicate/over cap) still get a fallback UI; only the
        // support code is unavailable.
        this.setState({ reportedRequestId: report?.request_id || null });
        if (typeof this.props.onError === 'function') {
            this.props.onError(error, info);
        }
    }

    componentDidUpdate(prevProps) {
        // Navigating away from a broken route must clear the fallback, otherwise
        // one bad page traps the user until a full reload.
        if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
            this.setState({ error: null, reportedRequestId: null });
        }
    }

    handleRetry() {
        this.setState({ error: null, reportedRequestId: null });
        if (typeof this.props.onReset === 'function') {
            this.props.onReset();
        }
    }

    handleReload() {
        if (typeof window !== 'undefined') {
            window.location.reload();
        }
    }

    render() {
        if (!this.state.error) {
            return this.props.children;
        }

        if (this.props.fallback) {
            return this.props.fallback;
        }

        const { reportedRequestId } = this.state;

        return (
            <div
                role="alert"
                className="max-w-7xl mx-auto flex items-center justify-center min-h-[60vh] p-4"
            >
                <div className="text-center card max-w-md">
                    <HiOutlineExclamationTriangle className="w-12 h-12 text-amber-400 mx-auto mb-4" />
                    <h2 className="text-lg font-semibold text-white mb-2">
                        {this.props.title || 'Something went wrong'}
                    </h2>
                    <p className="text-slate-400">
                        This section failed to load. The error has been reported and the rest
                        of the app is still usable.
                    </p>
                    {reportedRequestId && (
                        <p className="mt-3 text-xs text-slate-500">
                            Reference code:{' '}
                            <span className="font-mono text-slate-300">{reportedRequestId}</span>
                        </p>
                    )}
                    <div className="mt-6 flex items-center justify-center gap-3">
                        <button
                            type="button"
                            onClick={this.handleRetry}
                            className="btn-primary inline-flex items-center justify-center gap-2"
                        >
                            <HiArrowPath className="w-4 h-4" />
                            Try again
                        </button>
                        <button
                            type="button"
                            onClick={this.handleReload}
                            className="px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800"
                        >
                            Reload page
                        </button>
                    </div>
                </div>
            </div>
        );
    }
}

export default ErrorBoundary;
