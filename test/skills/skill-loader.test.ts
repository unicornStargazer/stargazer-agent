import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { composeSystemPrompt, loadAgentSkills } from '../../src/skills/index.js';

const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true })),
  );
});

describe('loadAgentSkills', () => {
  it('loads only the Skill identity and business instructions', async () => {
    const skillsDirectory = await createSkillsDirectory();
    await writeSkill(
      skillsDirectory,
      'order-support',
      ['name: Order Support'],
      'Help users check order status. Never invent an order result.',
    );
    await mkdir(join(skillsDirectory, 'not-a-skill'));

    await expect(loadAgentSkills({ directory: skillsDirectory })).resolves.toEqual([
      {
        id: 'order-support',
        name: 'Order Support',
        instructions: 'Help users check order status. Never invent an order result.',
      },
    ]);
  });

  it('rejects model and history settings in a Skill document', async () => {
    const skillsDirectory = await createSkillsDirectory();
    await writeSkill(skillsDirectory, 'with-model', ['name: Support', 'model: gpt-4.1-mini'], 'Help');

    await expect(loadAgentSkills({ directory: skillsDirectory })).rejects.toThrow(
      "Skill 'model' is not allowed",
    );
  });
});

describe('composeSystemPrompt', () => {
  it('adds every globally enabled Skill instruction to a Profile prompt', () => {
    expect(
      composeSystemPrompt('Respond concisely.', [
        { id: 'order-support', name: 'Order Support', instructions: 'Ask for the order number.' },
      ]),
    ).toBe(
      'Respond concisely.\n\n<skill name="Order Support">\nAsk for the order number.\n</skill>',
    );
  });
});

async function createSkillsDirectory(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), 'stargazer-agent-skills-'));
  temporaryDirectories.push(directory);
  return directory;
}

async function writeSkill(
  skillsDirectory: string,
  skillDirectoryName: string,
  frontMatter: readonly string[],
  instructions: string,
): Promise<void> {
  const directory = join(skillsDirectory, skillDirectoryName);
  await mkdir(directory, { recursive: true });
  await writeFile(
    join(directory, 'SKILL.md'),
    `---\n${frontMatter.join('\n')}\n---\n${instructions}\n`,
    'utf8',
  );
}
