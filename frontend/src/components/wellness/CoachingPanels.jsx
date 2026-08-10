/**
 * The coaching half of the client view: the Daily Plan.
 */
import React from 'react';
import DailyPlan from './DailyPlan';

export default function CoachingPanels({
  digest,
  behavioral,
  clientName,
  timezone,
  errors,
  onRetry,
}) {
  return (
    <DailyPlan
      digest={digest}
      behavioral={behavioral}
      clientName={clientName}
      timezone={timezone}
      error={errors.recommendations}
      onRetry={onRetry}
    />
  );
}
