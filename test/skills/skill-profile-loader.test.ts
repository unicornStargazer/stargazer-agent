import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { loadSkillProfiles } from '../../src/skills/index.js';

const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true })),
  );
});

describe('loadSkillProfiles', () => {
  it('loads each SKILL.md directory as a business Agent Profile', async () => {
    const skillsDirectory = await createSkillsDirectory();
    await writeSkill(
      skillsDirectory,
      'order-support',
      ['name: Order Support', 'historyLimit: 18'],
      'Help users check order status. Never invent an order result.',
    );
    await writeSkill(
      skillsDirectory,
      'account-support',
      ['name: Account Support', 'model: support-model'],
      'Help users with account access questions.',
    );
    await mkdir(join(skillsDirectory, 'not-a-skill'));

    await expect(
      loadSkillProfiles({ directory: skillsDirectory, defaultModel: 'default-model' }),
    ).resolves.toEqual([
      {
        id: 'account-support',
        name: 'Account Support',
        model: 'support-model',
        systemPrompt: 'Help users with account access questions.',
        historyLimit: undefined,
      },
      {
        id: 'order-support',
        name: 'Order Support',
        model: 'default-model',
        systemPrompt: 'Help users check order status. Never invent an order result.',
        historyLimit: 18,
      },
    ]);
  });

  it('rejects incomplete or unsafe skill configuration', async () => {
    const skillsDirectory = await createSkillsDirectory();
    await writeSkill(skillsDirectory, 'unsafe id', ['name: Unsafe'], 'Instructions');

    await expect(
      loadSkillProfiles({ directory: skillsDirectory, defaultModel: 'default-model' }),
    ).rejects.toThrow('Skill directory name is invalid');
  });

  it('requires a name and non-empty instructions', async () => {
    const skillsDirectory = await createSkillsDirectory();
    await writeSkill(skillsDirectory, 'missing-name', [], 'Instructions');

    await expect(
      loadSkillProfiles({ directory: skillsDirectory, defaultModel: 'default-model' }),
    ).rejects.toThrow("Skill front matter requires 'name'");
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
