import { hrDetail } from '../team';

describe('the HR contact row', () => {
  it('keeps naming the current contact while a replacement is invited', () => {
    expect(hrDetail({ hrEmail: 'hr@example.com', hrInvited: 'next@example.com' })).toBe(
      'next@example.com is invited to take over; hr@example.com stays until they sign up (the link lasts 7 days)',
    );
  });

  it('says it is waiting when there is no contact yet', () => {
    expect(hrDetail({ hrEmail: null, hrInvited: 'first@example.com' })).toMatch(
      /^first@example.com is invited; waiting for them to sign up/,
    );
  });

  it('explains who gets alerts otherwise', () => {
    expect(hrDetail({ hrEmail: 'hr@example.com', hrInvited: null })).toMatch(/^Check-in alerts/);
  });
});
