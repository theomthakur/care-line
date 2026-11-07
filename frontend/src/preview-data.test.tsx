import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { Providers } from './Providers';
import { FollowUps } from './pages/FollowUps';
import { DEMO_CASES, DEMO_TASKS } from './fixtures';
import { summaryFromState } from './derive';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
describe('read-only hosted preview', () => {
  it('provides distinct sample conversations and a follow-up', () => {
    expect(new Set(DEMO_CASES.map((c) => c.call_id)).size).toBeGreaterThan(3);
    expect(DEMO_TASKS.length).toBeGreaterThan(0);
  });
  it('shows sample providers without requesting a backend', () => {
    const fetch = vi.spyOn(globalThis, 'fetch');
    render(<Providers fixture />);
    expect(screen.getByText('Dr. Omar Haddad')).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('shows read-only sample follow-ups without requesting a backend', () => {
    const fetch = vi.spyOn(globalThis, 'fetch');
    render(<FollowUps calls={DEMO_CASES.map(summaryFromState)} sampleTasks={DEMO_TASKS} onOpenCall={() => {}} onChanged={() => {}} canAct={false} />);
    expect(screen.getByText('Samira K.')).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();
  });
});
