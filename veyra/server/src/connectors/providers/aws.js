import { AWS_REGIONS, BUCKET_PURPOSES, PEOPLE } from '../../mock/pools.js';

export default {
  id: 'aws',
  name: 'Amazon Web Services',
  shortName: 'AWS',
  vendor: 'Amazon',
  color: '#ff9900',
  description: 'S3 exposure, IAM hygiene, network reachability and audit logging across regions.',
  authMethod: 'Cross-account IAM role (SecurityAudit policy)',
  docsUrl: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-user.html',
  scopes: ['SecurityAudit (AWS managed)', 'ViewOnlyAccess (AWS managed)'],
  credentialFields: [
    {
      name: 'roleArn',
      label: 'IAM Role ARN',
      placeholder: 'arn:aws:iam::123456789012:role/VeyraSecurityAudit',
      example: 'arn:aws:iam::482910375516:role/VeyraSecurityAudit',
      pattern: /^arn:aws:iam::\d{12}:role\/[\w+=,.@\-/]{1,64}$/,
      patternMessage: 'Expected arn:aws:iam::<12-digit account>:role/<name>',
      help: 'Role in your account that trusts Veyra and has the SecurityAudit policy attached.',
    },
    {
      name: 'externalId',
      label: 'External ID',
      placeholder: 'veyra-7f3a91',
      example: 'veyra-7f3a91',
      pattern: /^[\w+=,.@:/-]{2,1224}$/,
      required: false,
      help: 'Optional. Protects against the confused-deputy problem.',
    },
  ],
  accountFrom: ({ roleArn }) => {
    const accountId = roleArn.split(':')[4];
    return { key: accountId, label: `AWS account ${accountId}`, accountId };
  },
  templates: [
    {
      key: 's3-public-bucket',
      title: (r) => `S3 bucket ${r.name} is publicly readable`,
      severity: 'critical',
      category: 'Data Exposure',
      exposure: 'public',
      exploitability: 1.5,
      count: [1, 2],
      resource: (rng, account) => {
        const name = `${rng.pick(['acme', 'prod', 'corp'])}-${rng.pick(BUCKET_PURPOSES)}-${rng.alnum(4, 'abcdefghijklmnopqrstuvwxyz0123456789')}`;
        return {
          id: `arn:aws:s3:::${name}`,
          name,
          type: 'S3 bucket',
          location: rng.pick(AWS_REGIONS),
          objects: rng.int(1200, 480000),
          sizeGb: rng.int(3, 900),
          accountId: account.accountId,
        };
      },
      explain: (r) =>
        `Bucket ${r.name} (${r.location}) has a bucket policy granting s3:GetObject to "*" and Block Public Access is off. ` +
        `Its ${r.objects.toLocaleString('en-US')} objects (${r.sizeGb} GB) can be listed and downloaded by anyone on the internet, ` +
        `and automated scanners find open buckets within hours.`,
      impact: 'Mass data leak of everything stored in the bucket.',
      remediation: [
        'Enable S3 Block Public Access on the bucket and at account level.',
        'Remove the "Principal": "*" statement from the bucket policy.',
        'If public delivery is needed, serve objects through CloudFront with origin access control.',
        'Review S3 server access logs for anonymous GET requests.',
      ],
      effort: '10 min',
      frameworks: ['CIS AWS 2.1.4', 'SOC 2 C1.1', 'GDPR Art. 32'],
      evidence: (r) => ({ blockPublicAccess: false, policyPrincipal: '*', actions: ['s3:GetObject', 's3:ListBucket'], region: r.location }),
    },
    {
      key: 'root-no-mfa',
      title: 'Root account has no MFA and an active access key',
      severity: 'critical',
      category: 'Identity',
      exposure: 'external',
      exploitability: 1.4,
      resource: (rng, account) => ({ id: `arn:aws:iam::${account.accountId}:root`, name: 'root', type: 'IAM root user', lastUsedDays: rng.int(2, 40) }),
      explain: (r, account) =>
        `The root user of account ${account.accountId} signs in with a password only and still has a programmatic access key, ` +
        `last used ${r.lastUsedDays} days ago. Root cannot be restricted by IAM policies, so its compromise is a full account takeover.`,
      impact: 'Complete, unrestricted control of the AWS account, including deletion of backups.',
      remediation: [
        'Enable a hardware or passkey MFA device on the root user.',
        'Delete the root access key and use IAM roles for automation.',
        'Store root credentials in a break-glass process with alerting on use.',
      ],
      effort: '10 min',
      frameworks: ['CIS AWS 1.4', 'CIS AWS 1.5', 'SOC 2 CC6.1'],
    },
    {
      key: 'sg-open-ssh',
      title: (r) => `Security group ${r.name} allows SSH from 0.0.0.0/0`,
      severity: 'high',
      category: 'Network',
      exposure: 'public',
      exploitability: 1.2,
      count: [1, 3],
      resource: (rng) => {
        const id = `sg-0${rng.hex(16)}`;
        const port = rng.pick([22, 22, 3389]);
        return { id, name: id, type: 'EC2 security group', location: rng.pick(AWS_REGIONS), port, instances: rng.int(1, 9) };
      },
      explain: (r) =>
        `${r.name} in ${r.location} accepts inbound TCP ${r.port} from any IPv4 address and is attached to ${r.instances} running instance(s). ` +
        `Internet-wide brute force against ${r.port === 22 ? 'SSH' : 'RDP'} is constant.`,
      impact: 'Direct remote-access attack surface on production hosts.',
      remediation: [
        'Remove the 0.0.0.0/0 inbound rule for the remote-access port.',
        'Use AWS Systems Manager Session Manager or a VPN for administrative access.',
        'Add an AWS Config rule (restricted-ssh) to prevent recurrence.',
      ],
      effort: '10 min',
      frameworks: ['CIS AWS 5.2', 'SOC 2 CC6.6'],
      evidence: (r) => ({ protocol: 'tcp', port: r.port, cidr: '0.0.0.0/0', attachedInstances: r.instances }),
    },
    {
      key: 'cloudtrail-disabled',
      title: (r) => `CloudTrail logging disabled in ${r.location}`,
      severity: 'high',
      category: 'Logging',
      exposure: 'internal',
      resource: (rng, account) => {
        const region = rng.pick(AWS_REGIONS);
        return { id: `${account.accountId}:${region}:cloudtrail`, name: `CloudTrail (${region})`, type: 'CloudTrail', location: region };
      },
      explain: (r) =>
        `No trail records management events in ${r.location}. Attackers routinely launch resources in regions nobody watches, ` +
        `and without logs there is no way to investigate what happened there.`,
      impact: 'Blind spot for incident response and compliance evidence.',
      remediation: [
        'Create or update an organization trail that covers all regions.',
        'Send logs to a dedicated, write-protected log archive account.',
        'Enable log file validation.',
      ],
      effort: '15 min',
      frameworks: ['CIS AWS 3.1', 'SOC 2 CC7.2'],
    },
    {
      key: 'stale-access-keys',
      title: (r) => `IAM user ${r.name} has an access key older than ${r.ageDays} days`,
      severity: 'medium',
      category: 'Identity',
      exposure: 'internal',
      count: [2, 4],
      resource: (rng, account) => {
        const name = rng.pick([...PEOPLE.slice(0, 8), 'ci-deployer', 'legacy-backup', 'terraform']);
        return { id: `arn:aws:iam::${account.accountId}:user/${name}`, name, type: 'IAM user', ageDays: rng.int(120, 900) };
      },
      explain: (r) =>
        `The access key for ${r.name} was created ${r.ageDays} days ago and never rotated. Long-lived keys end up in laptops, ` +
        `CI logs and old repositories, and the longer they live the more places they leak from.`,
      impact: 'Persistent programmatic access if the key has leaked anywhere.',
      remediation: [
        'Create a new key, update consumers, then deactivate and delete the old key.',
        'Prefer IAM roles or IAM Identity Center over long-lived user keys.',
      ],
      effort: '20 min',
      frameworks: ['CIS AWS 1.14', 'SOC 2 CC6.1'],
    },
    {
      key: 'rds-public',
      title: (r) => `RDS instance ${r.name} is publicly accessible`,
      severity: 'high',
      category: 'Network',
      exposure: 'public',
      probability: 0.7,
      resource: (rng, account) => {
        const name = `${rng.pick(['orders', 'users', 'analytics', 'billing'])}-db-${rng.pick(['prod', 'staging'])}`;
        return { id: `arn:aws:rds:${rng.pick(AWS_REGIONS)}:${account.accountId}:db:${name}`, name, type: 'RDS instance', engine: rng.pick(['postgres 15', 'mysql 8.0']) };
      },
      explain: (r) =>
        `${r.name} (${r.engine}) has PubliclyAccessible=true and resolves to a public IP. The only thing between ` +
        `the internet and your data is the database password.`,
      impact: 'Database exposed to credential brute force and engine exploits.',
      remediation: [
        'Set PubliclyAccessible to false and move the instance to private subnets.',
        'Restrict the security group to application subnets only.',
      ],
      effort: '30 min',
      frameworks: ['CIS AWS 2.3.3', 'SOC 2 CC6.6'],
    },
    {
      key: 'ebs-unencrypted',
      title: (r) => `${r.count} EBS volumes are not encrypted`,
      severity: 'low',
      category: 'Configuration',
      exposure: 'internal',
      resource: (rng, account) => ({ id: `${account.accountId}:ebs`, name: 'EBS volumes', type: 'EBS', count: rng.int(3, 22) }),
      explain: (r) =>
        `${r.count} EBS volumes and their snapshots are stored without encryption at rest, and default EBS encryption is off for the account.`,
      impact: 'Snapshots shared or copied by mistake expose raw disk contents.',
      remediation: [
        'Enable EBS encryption by default in every region.',
        'Re-create unencrypted volumes from encrypted snapshot copies during the next maintenance window.',
      ],
      effort: '1 hr',
      frameworks: ['CIS AWS 2.2.1', 'ISO 27001 A.8.24'],
    },
  ],
};
