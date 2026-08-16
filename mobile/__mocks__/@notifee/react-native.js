/**
 * Manual mock for the Notifee native module (spec §6.1).
 *
 * Jest picks this up automatically for every suite — the real package binds to
 * Android and cannot load under Node. Enum values are copied verbatim from
 * `@notifee/react-native/dist/types/*` so assertions match the real payloads.
 */
const AlarmType = {
    SET: 0,
    SET_AND_ALLOW_WHILE_IDLE: 1,
    SET_EXACT: 2,
    SET_EXACT_AND_ALLOW_WHILE_IDLE: 3,
    SET_ALARM_CLOCK: 4,
};

const TriggerType = { TIMESTAMP: 0, INTERVAL: 1 };

const RepeatFrequency = { NONE: -1, HOURLY: 0, DAILY: 1, WEEKLY: 2 };

const AndroidImportance = { NONE: 0, MIN: 1, LOW: 2, DEFAULT: 3, HIGH: 4 };

const AndroidVisibility = { SECRET: -1, PRIVATE: 0, PUBLIC: 1 };

const AndroidCategory = {
    ALARM: 'alarm',
    CALL: 'call',
    EVENT: 'event',
    MESSAGE: 'msg',
    REMINDER: 'reminder',
    SERVICE: 'service',
};

const EventType = {
    UNKNOWN: -1,
    DISMISSED: 0,
    PRESS: 1,
    ACTION_PRESS: 2,
    DELIVERED: 3,
    APP_BLOCKED: 4,
    CHANNEL_BLOCKED: 5,
    CHANNEL_GROUP_BLOCKED: 6,
    TRIGGER_NOTIFICATION_CREATED: 7,
    FG_ALREADY_EXIST: 8,
};

const AuthorizationStatus = {
    NOT_DETERMINED: -1,
    DENIED: 0,
    AUTHORIZED: 1,
    PROVISIONAL: 2,
};

const notifee = {
    createChannel: jest.fn(async () => 'icap-alarm'),
    deleteChannel: jest.fn(async () => undefined),
    getChannel: jest.fn(async () => null),
    createTriggerNotification: jest.fn(async () => 'notification-id'),
    getTriggerNotifications: jest.fn(async () => []),
    getTriggerNotificationIds: jest.fn(async () => []),
    cancelTriggerNotification: jest.fn(async () => undefined),
    cancelTriggerNotifications: jest.fn(async () => undefined),
    cancelAllNotifications: jest.fn(async () => undefined),
    cancelNotification: jest.fn(async () => undefined),
    displayNotification: jest.fn(async () => 'notification-id'),
    stopForegroundService: jest.fn(async () => undefined),
    requestPermission: jest.fn(async () => ({
        authorizationStatus: AuthorizationStatus.AUTHORIZED,
    })),
    getNotificationSettings: jest.fn(async () => ({
        authorizationStatus: AuthorizationStatus.AUTHORIZED,
    })),
    onForegroundEvent: jest.fn(() => jest.fn()),
    onBackgroundEvent: jest.fn(),
    getInitialNotification: jest.fn(async () => null),
    openAlarmPermissionSettings: jest.fn(async () => undefined),
    openBatteryOptimizationSettings: jest.fn(async () => undefined),
    isBatteryOptimizationEnabled: jest.fn(async () => false),
};

module.exports = {
    __esModule: true,
    default: notifee,
    AlarmType,
    AndroidCategory,
    AndroidImportance,
    AndroidVisibility,
    AuthorizationStatus,
    EventType,
    RepeatFrequency,
    TriggerType,
};
