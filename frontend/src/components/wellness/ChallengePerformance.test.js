/**
 * Challenge Performance panel — how the coach view reports category rankings
 * when the backend could only rank one category, or none at all.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import ChallengePerformance from './ChallengePerformance';

const clientRow = { timezone: 'UTC' };

function challengeWith(overrides) {
  return {
    total_attempts: 6,
    correct_attempts: 4,
    correct_answers: 4,
    accuracy: 66.7,
    avg_response_time: 12.4,
    total_points_earned: 40,
    by_type: { math: { accuracy: 75, total: 6 } },
    best_type: null,
    worst_type: null,
    trend: { direction: 'insufficient_data', accuracy_change: 0 },
    recent_activity: [],
    ...overrides,
  };
}

describe('ChallengePerformance category ranking', () => {
  test('a single ranked category is reported as the only category, not best vs worst', () => {
    render(
      <ChallengePerformance
        challenge={challengeWith({ best_type: 'math', worst_type: 'math' })}
        clientRow={clientRow}
      />
    );

    expect(screen.getByText('Only category with data')).toBeInTheDocument();
    expect(screen.getByText('math · 75%')).toBeInTheDocument();
    expect(screen.queryByText('Strongest category')).not.toBeInTheDocument();
    expect(screen.queryByText('Weakest category')).not.toBeInTheDocument();
  });

  test('no ranked category asks for more attempts instead of showing a winner', () => {
    render(<ChallengePerformance challenge={challengeWith()} clientRow={clientRow} />);

    expect(screen.getByText('Strongest category')).toBeInTheDocument();
    expect(screen.getByText('Weakest category')).toBeInTheDocument();
    expect(screen.getAllByText('Needs 2+ attempts in a category')).toHaveLength(2);
    expect(screen.queryByText('Only category with data')).not.toBeInTheDocument();
  });

  test('an insufficient-data trend shows no change value and no trend chip', () => {
    render(<ChallengePerformance challenge={challengeWith()} clientRow={clientRow} />);

    expect(screen.getByText('Accuracy change')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('Improving')).not.toBeInTheDocument();
    expect(screen.queryByText('Not enough data')).not.toBeInTheDocument();
  });

  test('no attempts at all renders the empty-data message', () => {
    render(
      <ChallengePerformance
        challenge={challengeWith({ total_attempts: 0, by_type: {} })}
        clientRow={clientRow}
      />
    );

    expect(
      screen.getByText(/Accuracy by puzzle type appears once this client solves alarm challenges/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('Only category with data')).not.toBeInTheDocument();
  });
});

describe('ChallengePerformance completion rate', () => {
  const completionWith = (overrides) => ({
    days: 30,
    served: 8,
    completed: 6,
    timed_out: 1,
    abandoned: 1,
    in_flight: 0,
    completion_rate: 75,
    timeout_rate: 12.5,
    abandonment_rate: 12.5,
    status: 'ok',
    ...overrides,
  });

  test('completion is reported separately from accuracy', () => {
    render(
      <ChallengePerformance
        challenge={challengeWith({ completion: completionWith() })}
        clientRow={clientRow}
      />
    );

    expect(screen.getByText('Challenge completion')).toBeInTheDocument();
    expect(screen.getByText('75%')).toBeInTheDocument();
    expect(
      screen.getByText(/Finished 6 of 8 challenges served/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/1 timed out/i)).toBeInTheDocument();
    expect(screen.getByText(/1 left unanswered/i)).toBeInTheDocument();
  });

  test('challenges served but never answered still report a completion rate', () => {
    render(
      <ChallengePerformance
        challenge={challengeWith({
          total_attempts: 0,
          by_type: {},
          completion: completionWith({
            served: 3,
            completed: 0,
            timed_out: 1,
            abandoned: 2,
            completion_rate: 0,
          }),
        })}
        clientRow={clientRow}
      />
    );

    expect(screen.getByText('Challenge completion')).toBeInTheDocument();
    expect(screen.getByText('0%')).toBeInTheDocument();
    expect(
      screen.getByText(/Finished 0 of 3 challenges served/i)
    ).toBeInTheDocument();
  });

  test('nothing served yet hides the block instead of showing 0%', () => {
    render(
      <ChallengePerformance
        challenge={challengeWith({
          completion: completionWith({
            served: 0,
            completed: 0,
            timed_out: 0,
            abandoned: 0,
            completion_rate: 0,
            status: 'no_data',
          }),
        })}
        clientRow={clientRow}
      />
    );

    expect(screen.queryByText('Challenge completion')).not.toBeInTheDocument();
  });
});
