/**
 * The coach-assignment surface is what grants a coach access to a client, so
 * these cover the create and revoke paths end to end through the component.
 */
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import AdminCoachAssignments from './AdminCoachAssignments';
import { adminAPI } from '../services/api';

jest.mock('../services/api', () => ({
  adminAPI: {
    listCoachAssignments: jest.fn(),
    createCoachAssignment: jest.fn(),
    removeCoachAssignment: jest.fn(),
    listUsers: jest.fn(),
  },
  readErrorDetail: jest.fn(),
}));

jest.mock('react-hot-toast', () => ({
  __esModule: true,
  default: { success: jest.fn(), error: jest.fn() },
}));

const ASSIGNMENT = {
  id: 7,
  coach_id: 2,
  coach_username: 'coach1',
  coach_full_name: 'Cody Coach',
  client_id: 5,
  client_username: 'client1',
  client_full_name: 'Eva Everyday',
  client_email: 'eva@example.com',
  is_active: true,
  notes: 'Morning routine focus',
  created_at: '2026-08-01T09:00:00Z',
};

function listResponse(assignments = [ASSIGNMENT]) {
  return {
    data: {
      total: assignments.length,
      page: 1,
      per_page: 10,
      total_pages: 1,
      assignments,
    },
  };
}

beforeEach(() => {
  // CRA's Jest preset sets resetMocks, so implementations belong here.
  adminAPI.listCoachAssignments.mockResolvedValue(listResponse());
  adminAPI.createCoachAssignment.mockResolvedValue({ data: ASSIGNMENT });
  adminAPI.removeCoachAssignment.mockResolvedValue({});
  adminAPI.listUsers.mockImplementation(({ role }) =>
    Promise.resolve({
      data: {
        users:
          role === 'wellness_coach'
            ? [{ id: 2, username: 'coach1', full_name: 'Cody Coach', email: 'cody@example.com' }]
            : [{ id: 5, username: 'client1', full_name: 'Eva Everyday', email: 'eva@example.com' }],
      },
    })
  );
  require('../services/api').readErrorDetail.mockResolvedValue('');
});

describe('AdminCoachAssignments', () => {
  it('lists existing assignments with both parties', async () => {
    render(<AdminCoachAssignments />);

    expect(await screen.findByText('Cody Coach')).toBeInTheDocument();
    expect(screen.getByText('Eva Everyday')).toBeInTheDocument();
    expect(screen.getByText('eva@example.com')).toBeInTheDocument();
    expect(screen.getByText('Morning routine focus')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('assigns a client to a coach and reloads the roster', async () => {
    render(<AdminCoachAssignments />);
    await screen.findByText('Cody Coach');

    fireEvent.change(await screen.findByLabelText('Coach'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Client'), { target: { value: '5' } });
    fireEvent.change(screen.getByLabelText('Assignment notes'), {
      target: { value: 'Sleep consistency' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Assign/ }));

    await waitFor(() =>
      expect(adminAPI.createCoachAssignment).toHaveBeenCalledWith({
        coach_id: 2,
        client_id: 5,
        notes: 'Sleep consistency',
      })
    );
    // The list must be re-read so the new row is server-confirmed.
    await waitFor(() =>
      expect(adminAPI.listCoachAssignments.mock.calls.length).toBeGreaterThan(1)
    );
  });

  it('requires both parties before the assign button is usable', async () => {
    render(<AdminCoachAssignments />);
    await screen.findByText('Cody Coach');

    expect(screen.getByRole('button', { name: /Assign/ })).toBeDisabled();
    fireEvent.change(await screen.findByLabelText('Coach'), { target: { value: '2' } });
    expect(screen.getByRole('button', { name: /Assign/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Client'), { target: { value: '5' } });
    expect(screen.getByRole('button', { name: /Assign/ })).toBeEnabled();
  });

  it('confirms before revoking a coach\u2019s access', async () => {
    render(<AdminCoachAssignments />);
    await screen.findByText('Cody Coach');

    fireEvent.click(screen.getByLabelText('Remove client1 from coach1'));
    expect(await screen.findByText('Remove assignment?')).toBeInTheDocument();
    expect(adminAPI.removeCoachAssignment).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    await waitFor(() =>
      expect(adminAPI.removeCoachAssignment).toHaveBeenCalledWith(2, 5)
    );
  });

  it('shows an empty state rather than a blank panel', async () => {
    adminAPI.listCoachAssignments.mockResolvedValue(listResponse([]));
    render(<AdminCoachAssignments />);

    expect(await screen.findByText('No coach assignments yet')).toBeInTheDocument();
  });

  it('surfaces a load failure instead of pretending there are none', async () => {
    adminAPI.listCoachAssignments.mockRejectedValue(new Error('boom'));
    render(<AdminCoachAssignments />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Failed to load assignments'
    );
  });
});
