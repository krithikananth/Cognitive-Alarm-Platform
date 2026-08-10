/**
 * Regression guard for the custom-range export validation.
 *
 * Switching to "Custom range" clears both dates. Without this guard the export
 * button still fired a request, and because `dateParams` silently falls back to
 * `{ days }` when either date is missing, the user was handed a file for the
 * wrong period instead of being told to finish picking the range.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import toast from 'react-hot-toast';
import { reportsAPI } from '../services/api';
import Reports from './Reports';

// Factories must not close over outer consts — jest.mock is hoisted above them.
jest.mock('../services/api', () => ({
    __esModule: true,
    reportsAPI: { list: jest.fn(), get: jest.fn(), export: jest.fn() },
    readErrorDetail: async (_err, fallback) => fallback,
}));

jest.mock('react-hot-toast', () => ({
    __esModule: true,
    default: { error: jest.fn(), success: jest.fn() },
}));

const REPORT = {
    report_type: 'habit',
    title: 'Habit Report',
    description: 'Habit formation overview',
    period: { start_date: '2026-07-12', end_date: '2026-08-10', days: 30 },
    is_empty: false,
    sections: { summary: { habit_score: 72.5 } },
    insights: [],
};

beforeEach(() => {
    jest.clearAllMocks();
    reportsAPI.list.mockResolvedValue({
        data: { reports: [{ type: 'habit', title: 'Habit', description: 'Habit report' }] },
    });
    reportsAPI.get.mockResolvedValue({ data: REPORT });
    reportsAPI.export.mockResolvedValue({
        data: new Blob(['%PDF-1.4']),
        headers: { 'content-type': 'application/pdf', 'content-disposition': '' },
    });
});

async function renderReports() {
    render(<Reports />);
    await waitFor(() => expect(reportsAPI.get).toHaveBeenCalled());
    // The export buttons stay disabled until the first load settles.
    await waitFor(() =>
        expect(screen.getByRole('button', { name: /^pdf$/i })).not.toBeDisabled(),
    );
}

describe('Reports custom-range export guard', () => {
    test('exporting with an unfinished custom range is blocked, not silently rescoped', async () => {
        await renderReports();

        fireEvent.click(screen.getByRole('button', { name: /custom range/i }));
        // Switching ranges makes loadReport complain too; clear it so the
        // assertion below can only be satisfied by the export click itself.
        await waitFor(() => expect(toast.error).toHaveBeenCalled());
        jest.clearAllMocks();

        fireEvent.click(screen.getByRole('button', { name: /^pdf$/i }));

        await waitFor(() =>
            expect(toast.error).toHaveBeenCalledWith('Select both start and end dates'),
        );
        expect(reportsAPI.export).not.toHaveBeenCalled();
    });

    test('exporting with the default day window still works', async () => {
        await renderReports();

        fireEvent.click(screen.getByRole('button', { name: /^pdf$/i }));

        await waitFor(() => expect(reportsAPI.export).toHaveBeenCalledTimes(1));
        expect(reportsAPI.export).toHaveBeenCalledWith('habit', 'pdf', { days: 30 });
    });
});
