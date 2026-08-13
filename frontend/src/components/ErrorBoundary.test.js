/**
 * Error boundary: containment, recovery and reporting.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import ErrorBoundary from './ErrorBoundary';
import { reportClientError } from '../services/errorReporting';

jest.mock('../services/errorReporting', () => ({
    reportClientError: jest.fn(),
}));

function Boom({ explode = true }) {
    if (explode) throw new Error('render exploded');
    return <div>recovered content</div>;
}

let consoleError;

beforeEach(() => {
    // CRA's Jest preset sets resetMocks:true, which strips any implementation
    // given to jest.fn() in the module factory — so it is (re)applied here.
    reportClientError.mockReturnValue({ request_id: 'trace-abc-123' });
    // React logs every caught boundary error; that noise is expected here.
    consoleError = jest.spyOn(console, 'error').mockImplementation(() => { });
});

afterEach(() => {
    consoleError.mockRestore();
});

describe('normal rendering', () => {
    it('renders children when nothing throws', () => {
        render(
            <ErrorBoundary name="test">
                <div>healthy content</div>
            </ErrorBoundary>
        );
        expect(screen.getByText('healthy content')).toBeInTheDocument();
    });

    it('reports nothing when nothing throws', () => {
        render(
            <ErrorBoundary name="test">
                <div>healthy content</div>
            </ErrorBoundary>
        );
        expect(reportClientError).not.toHaveBeenCalled();
    });
});

describe('containment', () => {
    it('renders a fallback instead of a blank page', () => {
        render(
            <ErrorBoundary name="test">
                <Boom />
            </ErrorBoundary>
        );

        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    });

    it('keeps sibling content mounted', () => {
        render(
            <div>
                <div>app shell</div>
                <ErrorBoundary name="test">
                    <Boom />
                </ErrorBoundary>
            </div>
        );

        expect(screen.getByText('app shell')).toBeInTheDocument();
        expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    it('uses a custom title when given one', () => {
        render(
            <ErrorBoundary name="test" title="Dashboard unavailable">
                <Boom />
            </ErrorBoundary>
        );
        expect(screen.getByText('Dashboard unavailable')).toBeInTheDocument();
    });

    it('uses a custom fallback element when given one', () => {
        render(
            <ErrorBoundary name="test" fallback={<div>custom fallback</div>}>
                <Boom />
            </ErrorBoundary>
        );
        expect(screen.getByText('custom fallback')).toBeInTheDocument();
    });
});

describe('reporting', () => {
    it('reports the error with the boundary context', () => {
        render(
            <ErrorBoundary name="route">
                <Boom />
            </ErrorBoundary>
        );

        expect(reportClientError).toHaveBeenCalledTimes(1);
        const [error, options] = reportClientError.mock.calls[0];
        expect(error.message).toBe('render exploded');
        expect(options.source).toBe('error_boundary');
        expect(options.boundary).toBe('route');
        expect(options.componentStack).toEqual(expect.any(String));
    });

    it('shows the reference code so a user can quote it to support', () => {
        render(
            <ErrorBoundary name="route">
                <Boom />
            </ErrorBoundary>
        );
        expect(screen.getByText('trace-abc-123')).toBeInTheDocument();
    });

    it('still renders a fallback when the report was suppressed', () => {
        reportClientError.mockReturnValueOnce(null);
        render(
            <ErrorBoundary name="route">
                <Boom />
            </ErrorBoundary>
        );

        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.queryByText(/Reference code/)).not.toBeInTheDocument();
    });

    it('invokes an onError callback when provided', () => {
        const onError = jest.fn();
        render(
            <ErrorBoundary name="route" onError={onError}>
                <Boom />
            </ErrorBoundary>
        );
        expect(onError).toHaveBeenCalledTimes(1);
    });
});

describe('recovery', () => {
    it('re-renders the children when Try again is clicked', () => {
        function Flaky() {
            const [broken, setBroken] = React.useState(true);
            return (
                <ErrorBoundary name="route" onReset={() => setBroken(false)}>
                    <Boom explode={broken} />
                </ErrorBoundary>
            );
        }

        render(<Flaky />);
        expect(screen.getByRole('alert')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: /try again/i }));
        expect(screen.getByText('recovered content')).toBeInTheDocument();
    });

    it('clears the fallback when the reset key changes', () => {
        const { rerender } = render(
            <ErrorBoundary name="route" resetKey="/dashboard">
                <Boom />
            </ErrorBoundary>
        );
        expect(screen.getByRole('alert')).toBeInTheDocument();

        // Simulates navigating to another route.
        rerender(
            <ErrorBoundary name="route" resetKey="/alarms">
                <Boom explode={false} />
            </ErrorBoundary>
        );
        expect(screen.getByText('recovered content')).toBeInTheDocument();
    });

    it('offers a reload as a last resort', () => {
        render(
            <ErrorBoundary name="route">
                <Boom />
            </ErrorBoundary>
        );
        expect(
            screen.getByRole('button', { name: /reload page/i })
        ).toBeInTheDocument();
    });
});
