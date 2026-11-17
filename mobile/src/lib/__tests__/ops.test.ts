import {
  capLevel,
  capShare,
  dollars,
  latencyLevel,
  percent,
  rateLevel,
  seconds,
  words,
} from '../ops';

describe('operations page formatting', () => {
  it('formats rates, money and times, with a dash when missing', () => {
    expect(percent(0.934)).toBe('93%');
    expect(percent(null)).toBe('–');
    expect(dollars(0.0114)).toBe('$0.011');
    expect(dollars(12.5)).toBe('$12.50');
    expect(seconds(7.24)).toBe('7.2 s');
    expect(seconds(42.6)).toBe('43 s');
    expect(words('answered_in_part')).toBe('answered in part');
  });
  it('flags a cap at 70% and 90%, and never overfills the bar', () => {
    expect(capLevel(3, 5)).toBe('good');
    expect(capLevel(4, 5)).toBe('watch');
    expect(capLevel(4.6, 5)).toBe('bad');
    expect(capShare(9, 5)).toBe(1);
    expect(capShare(1, 0)).toBe(0);
  });
  it('reads higher rates as better and long answers as stuck', () => {
    expect(rateLevel(0.95)).toBe('good');
    expect(rateLevel(0.8)).toBe('watch');
    expect(rateLevel(0.5)).toBe('bad');
    expect(rateLevel(null)).toBe('watch');
    expect(latencyLevel(8)).toBe('good');
    expect(latencyLevel(30)).toBe('watch');
    expect(latencyLevel(90)).toBe('bad');
  });
});
