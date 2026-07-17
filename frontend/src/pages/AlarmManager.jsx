/**
 * Alarm Manager — full CRUD for alarm creation, editing, and management.
 */
import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useForm } from 'react-hook-form';
import {
  HiOutlineClock, HiOutlinePlus, HiOutlineTrash,
  HiOutlinePencilSquare, HiOutlineXMark, HiOutlineBell,
  HiOutlinePuzzlePiece, HiOutlineCalendarDays,
} from 'react-icons/hi2';
import toast from 'react-hot-toast';
import useAlarmStore from '../store/alarmStore';
import useActiveAlarmStore from '../store/activeAlarmStore';
import { userAPI } from '../services/api';

const ALARM_TYPES = [
  { value: 'daily', label: 'Daily', desc: 'Every day' },
  { value: 'weekday', label: 'Weekday', desc: 'Mon – Fri' },
  { value: 'weekend', label: 'Weekend', desc: 'Sat – Sun' },
  { value: 'one_time', label: 'One-Time', desc: 'Specific date' },
  { value: 'smart_adaptive', label: 'Smart', desc: 'AI-optimized' },
];

const CHALLENGE_TYPES = [
  { value: 'random', label: '🎲 Random' },
  { value: 'math', label: '🔢 Math' },
  { value: 'logic', label: '🧩 Logic' },
  { value: 'memory', label: '🧠 Memory' },
  { value: 'word_game', label: '📝 Word' },
  { value: 'pattern', label: '🔗 Pattern' },
  { value: 'riddle', label: '❓ Riddle' },
  { value: 'quiz', label: '📚 Quiz' },
];

const DIFFICULTY_LEVELS = [
  { value: 'beginner', label: 'Beginner', color: 'text-emerald-400' },
  { value: 'easy', label: 'Easy', color: 'text-green-400' },
  { value: 'medium', label: 'Medium', color: 'text-amber-400' },
  { value: 'hard', label: 'Hard', color: 'text-orange-400' },
  { value: 'expert', label: 'Expert', color: 'text-red-400' },
];

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const parseTimeTo12Hour = (value) => {
  const [hours = 7, minutes = 0] = (value || '07:00').split(':').map(Number);
  const normalizedHours = ((hours % 24) + 24) % 24;
  const period = normalizedHours >= 12 ? 'PM' : 'AM';
  let displayHour = normalizedHours % 12;
  if (displayHour === 0) displayHour = 12;
  return {
    hour: String(displayHour),
    minute: String(minutes).padStart(2, '0'),
    period,
  };
};

const formatTimeTo24Hour = ({ hour, minute, period }) => {
  let hour24 = Number(hour);
  if (hour24 === 12) hour24 = 0;
  if (period === 'PM') hour24 += 12;
  return `${String(hour24).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
};

export default function AlarmManager() {
  const { alarms, fetchAlarms, createAlarm, updateAlarm, deleteAlarm, toggleAlarm, isLoading } = useAlarmStore();
  const triggerAlarm = useActiveAlarmStore((s) => s.triggerAlarm);
  const [showModal, setShowModal] = useState(false);
  const [editingAlarm, setEditingAlarm] = useState(null);
  const [pendingDeleteId, setPendingDeleteId] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [defaultDifficulty, setDefaultDifficulty] = useState('medium');

  useEffect(() => {
    fetchAlarms();
    userAPI.getProfile()
      .then((res) => {
        const pref =
          res.data?.profile?.difficulty_preference ||
          res.data?.difficulty_preference ||
          'medium';
        setDefaultDifficulty(String(pref).toLowerCase());
      })
      .catch(() => {
        setDefaultDifficulty('medium');
      });
  }, []);

  const handleCreate = () => {
    setEditingAlarm(null);
    setShowModal(true);
  };

  const handleEdit = (alarm) => {
    setEditingAlarm(alarm);
    setShowModal(true);
  };

  const handleDeleteRequest = (id) => {
    setPendingDeleteId(id);
  };

  const handleDeleteConfirm = async () => {
    if (pendingDeleteId == null || isDeleting) return;
    setIsDeleting(true);
    try {
      const result = await deleteAlarm(pendingDeleteId);
      if (result.success) {
        toast.success('Alarm deleted');
        setPendingDeleteId(null);
      } else {
        toast.error(result.error || 'Failed to delete alarm');
      }
    } finally {
      setIsDeleting(false);
    }
  };

  const handleDeleteCancel = () => {
    if (isDeleting) return;
    setPendingDeleteId(null);
  };

  const handleToggle = async (alarm) => {
    await toggleAlarm(alarm.id, !alarm.is_active);
    toast.success(alarm.is_active ? 'Alarm disabled' : 'Alarm enabled');
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between"
      >
        <div>
          <h1 className="text-2xl font-bold text-white font-display flex items-center gap-2">
            <HiOutlineClock className="w-7 h-7 text-primary-400" />
            Alarm Manager
          </h1>
          <p className="text-slate-400 mt-1">{alarms.length} alarm{alarms.length !== 1 ? 's' : ''} configured</p>
        </div>
        <button onClick={handleCreate} className="btn-primary flex items-center gap-2" id="create-alarm-btn">
          <HiOutlinePlus className="w-5 h-5" /> New Alarm
        </button>
      </motion.div>

      {/* Alarm List */}
      {alarms.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="card text-center py-16"
        >
          <div className="w-20 h-20 rounded-full bg-primary-500/10 flex items-center justify-center mx-auto mb-4">
            <HiOutlineClock className="w-10 h-10 text-primary-400" />
          </div>
          <h3 className="text-xl font-semibold text-white mb-2">No Alarms Yet</h3>
          <p className="text-slate-400 mb-6 max-w-sm mx-auto">
            Create your first cognitive alarm and start building better wake-up habits.
          </p>
          <button onClick={handleCreate} className="btn-primary inline-flex items-center gap-2">
            <HiOutlinePlus className="w-5 h-5" /> Create Alarm
          </button>
        </motion.div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <AnimatePresence>
            {alarms.map((alarm, idx) => (
              <motion.div
                key={alarm.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ delay: idx * 0.05 }}
                className="card group"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-4">
                    <div className={`w-14 h-14 rounded-xl flex items-center justify-center ${alarm.is_active ? 'bg-primary-500/15' : 'bg-surface-700/50'}`}>
                      <span className={`text-xl font-bold ${alarm.is_active ? 'text-primary-400' : 'text-slate-500'}`}>
                        {alarm.alarm_time?.slice(0, 5)}
                      </span>
                    </div>
                    <div>
                      <p className="font-medium text-white">{alarm.label || 'Alarm'}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="badge-primary text-[10px]">{alarm.alarm_type?.replace('_', ' ')}</span>
                        {alarm.challenge_type && (
                          <span className="badge-warning text-[10px]">{alarm.challenge_type}</span>
                        )}
                        <span className={`text-[10px] ${DIFFICULTY_LEVELS.find(d => d.value === alarm.challenge_difficulty)?.color || 'text-slate-400'}`}>
                          {alarm.challenge_difficulty}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Toggle */}
                  <button
                    onClick={() => handleToggle(alarm)}
                    className={`toggle ${alarm.is_active ? 'toggle-active' : 'toggle-inactive'}`}
                  >
                    <span className={`toggle-knob ${alarm.is_active ? 'translate-x-5' : 'translate-x-1'}`} />
                  </button>
                </div>

                {/* Days */}
                {alarm.days_of_week?.length > 0 && (
                  <div className="flex gap-1.5 mt-3">
                    {DAYS.map((day, i) => (
                      <span
                        key={i}
                        className={`w-8 h-8 rounded-lg flex items-center justify-center text-[10px] font-medium ${
                          alarm.days_of_week?.includes(i)
                            ? 'bg-primary-500/20 text-primary-300 border border-primary-500/30'
                            : 'bg-surface-800/50 text-slate-600'
                        }`}
                      >
                        {day}
                      </span>
                    ))}
                  </div>
                )}

                {/* Details */}
                <div className="flex items-center gap-4 mt-3 text-xs text-slate-400">
                  <span className="flex items-center gap-1">
                    <HiOutlineBell className="w-3.5 h-3.5" />
                    {alarm.snooze_limit === 0
                      ? 'Anti-snooze'
                      : `Snooze: ${alarm.snooze_limit}x`}
                  </span>
                  <span className="flex items-center gap-1">
                    <HiOutlinePuzzlePiece className="w-3.5 h-3.5" />
                    {alarm.challenge_type || 'Any'}
                    {alarm.challenge_count > 1 ? ` ×${alarm.challenge_count}` : ''}
                  </span>
                </div>

                {/* Actions */}
                <div className="flex justify-end gap-2 mt-3">
                  <button
                    onClick={() => triggerAlarm(alarm.id)}
                    className="p-2 rounded-lg hover:bg-amber-500/10 transition"
                    title="Test Ring"
                    data-alarm-id={alarm.id}
                  >
                    <HiOutlineBell className="w-4 h-4 text-slate-400 hover:text-amber-400" />
                  </button>
                  <button onClick={() => handleEdit(alarm)} className="p-2 rounded-lg hover:bg-surface-700 transition" title="Edit">
                    <HiOutlinePencilSquare className="w-4 h-4 text-slate-400 hover:text-primary-400" />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      handleDeleteRequest(alarm.id);
                    }}
                    className="p-2 rounded-lg hover:bg-red-500/10 transition"
                    title="Delete"
                    id={`delete-alarm-${alarm.id}`}
                  >
                    <HiOutlineTrash className="w-4 h-4 text-slate-400 hover:text-red-400" />
                  </button>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}

      {/* Create/Edit Modal */}
      <AnimatePresence>
        {showModal && (
          <AlarmModal
            alarm={editingAlarm}
            defaultDifficulty={defaultDifficulty}
            onClose={() => setShowModal(false)}
            onCreate={createAlarm}
            onUpdate={updateAlarm}
          />
        )}
      </AnimatePresence>

      {/* Delete confirmation */}
      <AnimatePresence>
        {pendingDeleteId != null && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
          >
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={handleDeleteCancel} />
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="relative w-full max-w-sm glass rounded-2xl p-6 z-10"
            >
              <h2 className="text-lg font-bold text-white mb-2">Delete this alarm?</h2>
              <p className="text-sm text-slate-400 mb-6">
                This permanently removes the alarm and cannot be undone.
              </p>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={handleDeleteCancel}
                  disabled={isDeleting}
                  className="btn-secondary flex-1"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleDeleteConfirm}
                  disabled={isDeleting}
                  className="flex-1 px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-white font-medium transition disabled:opacity-50"
                  id="confirm-delete-alarm"
                >
                  {isDeleting ? 'Deleting...' : 'Delete'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}


// ═══════════════════════════════════════════
// Alarm Create/Edit Modal
// ═══════════════════════════════════════════

function AlarmModal({ alarm, defaultDifficulty = 'medium', onClose, onCreate, onUpdate }) {
  const isEdit = !!alarm;
  const initialDifficulty = alarm?.challenge_difficulty || defaultDifficulty || 'medium';
  const [timeSelection, setTimeSelection] = useState(() => parseTimeTo12Hour(alarm?.alarm_time?.slice(0, 5) || '07:00'));
  const { register, handleSubmit, watch, setValue, formState: { errors } } = useForm({
    defaultValues: alarm ? {
      label: alarm.label || '',
      alarm_time: alarm.alarm_time?.slice(0, 5) || '07:00',
      alarm_type: alarm.alarm_type || 'daily',
      challenge_type: alarm.challenge_type || 'random',
      challenge_difficulty: initialDifficulty,
      challenge_count: alarm.challenge_count ?? 1,
      snooze_limit: alarm.snooze_limit ?? 3,
      snooze_interval_minutes: alarm.snooze_interval_minutes ?? 5,
      one_time_date: alarm.one_time_date || '',
    } : {
      label: '',
      alarm_time: '07:00',
      alarm_type: 'daily',
      challenge_type: 'random',
      challenge_difficulty: initialDifficulty,
      challenge_count: 1,
      snooze_limit: 3,
      snooze_interval_minutes: 5,
      one_time_date: '',
    },
  });

  const selectedType = watch('alarm_type');

  const updateTimeSelection = (changes) => {
    const nextSelection = { ...timeSelection, ...changes };
    setTimeSelection(nextSelection);
    setValue('alarm_time', formatTimeTo24Hour(nextSelection), { shouldDirty: true, shouldValidate: true });
  };

  useEffect(() => {
    const initialTime = alarm?.alarm_time?.slice(0, 5) || '07:00';
    const parsedTime = parseTimeTo12Hour(initialTime);
    setTimeSelection(parsedTime);
    setValue('alarm_time', formatTimeTo24Hour(parsedTime), { shouldDirty: true, shouldValidate: true });
  }, [alarm, setValue]);

  const onSubmit = async (data) => {
    const payload = {
      title: data.label || 'Alarm',
      label: data.label || 'Alarm',
      alarm_time: data.alarm_time,
      alarm_type: data.alarm_type,
      challenge_type: data.challenge_type === 'word' ? 'word_game' : data.challenge_type,
      challenge_difficulty: data.challenge_difficulty || 'medium',
      challenge_count: parseInt(data.challenge_count, 10) || 1,
      snooze_limit: parseInt(data.snooze_limit, 10),
      snooze_interval_minutes: parseInt(data.snooze_interval_minutes, 10),
      one_time_date: data.alarm_type === 'one_time' ? data.one_time_date : null,
    };

    let result;
    if (isEdit) {
      result = await onUpdate(alarm.id, payload);
    } else {
      result = await onCreate(payload);
    }

    if (result.success) {
      toast.success(isEdit ? 'Alarm updated!' : 'Alarm created!');
      onClose();
    } else {
      toast.error(result.error || 'Failed to save alarm');
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        className="relative w-full max-w-lg max-h-[90vh] overflow-y-auto glass rounded-2xl p-6 z-10"
      >
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold text-white">
            {isEdit ? 'Edit Alarm' : 'Create New Alarm'}
          </h2>
          <button onClick={onClose} className="p-2 rounded-lg hover:bg-surface-700 transition">
            <HiOutlineXMark className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
          {/* Label */}
          <div>
            <label className="label">Label</label>
            <input
              type="text"
              placeholder="Morning Wake-up"
              className="input"
              id="alarm-label"
              {...register('label')}
            />
          </div>

          {/* Time */}
          <div>
            <label className="label">Alarm Time</label>
            <div className="flex items-center gap-2">
              <select
                className="input text-center text-lg font-semibold"
                value={timeSelection.hour}
                onChange={(e) => updateTimeSelection({ hour: e.target.value })}
              >
                {Array.from({ length: 12 }, (_, index) => {
                  const value = index + 1;
                  return (
                    <option key={value} value={value}>
                      {String(value).padStart(2, '0')}
                    </option>
                  );
                })}
              </select>
              <span className="text-slate-400 text-xl font-semibold">:</span>
              <select
                className="input text-center text-lg font-semibold"
                value={timeSelection.minute}
                onChange={(e) => updateTimeSelection({ minute: e.target.value })}
              >
                {Array.from({ length: 60 }, (_, index) => {
                  const value = String(index).padStart(2, '0');
                  return (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  );
                })}
              </select>
              <select
                className="input text-center text-lg font-semibold min-w-[72px]"
                value={timeSelection.period}
                onChange={(e) => updateTimeSelection({ period: e.target.value })}
              >
                <option value="AM">AM</option>
                <option value="PM">PM</option>
              </select>
            </div>
            <input type="hidden" id="alarm-time" {...register('alarm_time', { required: true })} />
            {errors.alarm_time && <p className="text-red-400 text-xs mt-1">Alarm time is required</p>}
          </div>

          {/* Alarm Type */}
          <div>
            <label className="label">Alarm Type</label>
            <div className="grid grid-cols-3 gap-2">
              {ALARM_TYPES.map((type) => (
                <label
                  key={type.value}
                  className={`flex flex-col items-center p-3 rounded-xl cursor-pointer border transition-all ${
                    watch('alarm_type') === type.value
                      ? 'border-primary-500 bg-primary-500/10'
                      : 'border-surface-700/50 hover:border-surface-600'
                  }`}
                >
                  <input
                    type="radio"
                    value={type.value}
                    className="hidden"
                    {...register('alarm_type')}
                  />
                  <span className="text-sm font-medium text-white">{type.label}</span>
                  <span className="text-[10px] text-slate-400">{type.desc}</span>
                </label>
              ))}
            </div>
          </div>

          {/* One-time date */}
          {selectedType === 'one_time' && (
            <div>
              <label className="label">Date</label>
              <input type="date" className="input" {...register('one_time_date', { required: selectedType === 'one_time' })} />
            </div>
          )}

          {/* Challenge Type */}
          <div>
            <label className="label">Challenge Type</label>
            <div className="grid grid-cols-4 gap-2">
              {CHALLENGE_TYPES.map((ct) => (
                <label
                  key={ct.value}
                  className={`flex items-center justify-center p-2.5 rounded-xl cursor-pointer border text-sm transition-all ${
                    watch('challenge_type') === ct.value
                      ? 'border-accent-500 bg-accent-500/10'
                      : 'border-surface-700/50 hover:border-surface-600'
                  }`}
                >
                  <input type="radio" value={ct.value} className="hidden" {...register('challenge_type')} />
                  <span>{ct.label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Difficulty */}
          <div>
            <label className="label">Difficulty</label>
            <div className="flex gap-2">
              {DIFFICULTY_LEVELS.map((d) => (
                <label
                  key={d.value}
                  className={`flex-1 text-center p-2 rounded-xl cursor-pointer border text-xs font-medium transition-all ${
                    watch('challenge_difficulty') === d.value
                      ? 'border-primary-500 bg-primary-500/10 text-white'
                      : 'border-surface-700/50 text-slate-400 hover:border-surface-600'
                  }`}
                >
                  <input type="radio" value={d.value} className="hidden" {...register('challenge_difficulty')} />
                  {d.label}
                </label>
              ))}
            </div>
          </div>

          {/* Consecutive challenges required to dismiss */}
          <div>
            <label className="label">Challenges to Dismiss (consecutive)</label>
            <input
              type="number"
              min="1"
              max="10"
              className="input"
              {...register('challenge_count')}
            />
            <p className="text-[11px] text-slate-500 mt-1">
              Wrong answers reset the streak — you must solve this many in a row.
            </p>
          </div>

          {/* Anti-snooze settings */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">Max Snoozes</label>
              <input type="number" min="0" max="10" className="input" {...register('snooze_limit')} />
              <p className="text-[11px] text-slate-500 mt-1">
                0 = anti-snooze (no snoozing). Each snooze raises challenge difficulty.
              </p>
            </div>
            <div>
              <label className="label">Snooze Interval (min)</label>
              <input type="number" min="1" max="30" className="input" {...register('snooze_interval_minutes')} />
              <p className="text-[11px] text-slate-500 mt-1">
                Delay before the alarm re-rings after a snooze.
              </p>
            </div>
          </div>

          {/* Submit */}
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
            <button type="submit" className="btn-primary flex-1" id="alarm-submit">
              {isEdit ? 'Save Changes' : 'Create Alarm'}
            </button>
          </div>
        </form>
      </motion.div>
    </motion.div>
  );
}
