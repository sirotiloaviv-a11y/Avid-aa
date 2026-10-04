// Remediation playbooks: one per security check (finding template).
//
// A playbook is the deterministic knowledge Veyra has about fixing a check:
//   - autoFix:   whether the Auto-Fix engine may apply it, the scoped permission
//                it needs, and if not, why a human has to do it;
//   - actions:   the API calls the Auto-Fix engine performs (simulated);
//   - scripts:   copy-pasteable remediation code (CLI, Terraform, PowerShell, API);
//   - sideEffects: what can break, to double-check before applying;
//   - rollback:  how to undo the change.
//
// The AI service uses playbooks as its rule-based fallback and as reference
// material for the LLM. Auto-Fix only ever executes playbook actions, never
// model-generated code.

const q = (value) => String(value ?? '').replace(/[^\w.@:/+=,-]/g, '');

const orgOf = (a) => a?.organization ?? 'your-org';
const domainOf = (a) => a?.domain ?? 'example.com';
const subOf = (a) => a?.subscriptionId ?? '<subscription-id>';
const workspaceOf = (a) => a?.workspace ?? 'your-workspace';

function manual(reason, permission = null) {
  return { supported: false, reason, permission };
}
function auto(permission) {
  return { supported: true, reason: null, permission };
}

const ISSUER_HINTS = {
  'AWS Access Key ID': 'aws iam update-access-key --user-name <owner> --access-key-id <AKIA...> --status Inactive',
  'Stripe Live Secret Key': 'Stripe Dashboard > Developers > API keys > Roll key (set expiry: now)',
  'Slack Bot Token': 'api.slack.com/apps > your app > OAuth & Permissions > Revoke tokens, then reinstall',
  'GCP Service Account Key': 'gcloud iam service-accounts keys delete <KEY_ID> --iam-account <sa>@<project>.iam.gserviceaccount.com',
  'PostgreSQL Connection String': 'ALTER ROLE admin WITH PASSWORD \'<new-strong-password>\'; -- then update the secret store',
};

const PLAYBOOKS = {
  // ------------------------------------------------------------------ GitHub
  'exposed-secret': {
    autoFix: (f) => manual(`The ${f.resource.secretType} must be revoked at its issuer. Rewriting git history alone does not invalidate it.`),
    actions: () => [],
    scripts: (f, a) => [{
      label: 'Revoke & purge',
      language: 'bash',
      code: [
        '# 1. Revoke the credential at the issuer FIRST (history rewrites do not invalidate it):',
        `#    ${ISSUER_HINTS[f.resource.secretType] ?? 'Rotate the credential in the issuing service.'}`,
        '',
        '# 2. Purge the file from history (coordinate with the team: this rewrites history)',
        `git clone --mirror git@github.com:${q(orgOf(a))}/${q(f.resource.repo)}.git`,
        `cd ${q(f.resource.repo)}.git`,
        `git filter-repo --path ${q(f.resource.file)} --invert-paths`,
        'git push --force --mirror',
        '',
        '# 3. Block the next leak before it lands',
        `gh api -X PATCH orgs/${q(orgOf(a))} \\`,
        '  -F secret_scanning_push_protection_enabled_for_new_repositories=true',
      ].join('\n'),
    }],
    sideEffects: [
      'Every service using the old credential fails as soon as it is revoked. Deploy the replacement secret first.',
      'Force-pushing rewritten history breaks open pull requests and existing clones; contributors must re-clone.',
      'Forks and caches outside your control keep the old history. Revocation is the real fix.',
    ],
    rollback: 'Revocation cannot be undone. Issue a new credential from the provider.',
  },
  'branch-protection-missing': {
    autoFix: () => auto('administration:write (repository rulesets)'),
    actions: (f, a) => [`POST /repos/${orgOf(a)}/${f.resource.repo}/rulesets {"name":"protect-default-branch"}`],
    scripts: (f, a) => [{
      label: 'GitHub CLI',
      language: 'bash',
      code: [
        `gh api -X POST repos/${q(orgOf(a))}/${q(f.resource.repo)}/rulesets --input - <<'JSON'`,
        '{',
        '  "name": "protect-default-branch",',
        '  "target": "branch",',
        '  "enforcement": "active",',
        '  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },',
        '  "rules": [',
        '    { "type": "deletion" },',
        '    { "type": "non_fast_forward" },',
        '    { "type": "pull_request", "parameters": {',
        '        "required_approving_review_count": 1,',
        '        "dismiss_stale_reviews_on_push": true,',
        '        "require_code_owner_review": false,',
        '        "require_last_push_approval": false,',
        '        "required_review_thread_resolution": false } }',
        '  ]',
        '}',
        'JSON',
      ].join('\n'),
    }],
    sideEffects: [
      'CI jobs, release scripts or bots that push directly to the default branch will be rejected. Add them as bypass actors.',
      'Hotfixes now need a pull request and an approval; make sure two people can approve out of hours.',
    ],
    rollback: 'Set the ruleset enforcement to "disabled" or delete it in Settings > Rules.',
  },
  'members-without-2fa': {
    autoFix: () => manual('Enforcing 2FA immediately removes every non-compliant member from the organization. Notify them and give a deadline first.'),
    actions: () => [],
    scripts: (f, a) => [{
      label: 'GitHub CLI',
      language: 'bash',
      code: [
        '# Members without 2FA (notify these people first)',
        `gh api --paginate "orgs/${q(orgOf(a))}/members?filter=2fa_disabled" --jq '.[].login'`,
        '',
        '# After the deadline: Settings > Authentication security >',
        '#   "Require two-factor authentication for everyone in the organization"',
      ].join('\n'),
    }],
    sideEffects: [
      'Members without 2FA are removed from the organization the moment enforcement is enabled, losing access and fork ownership.',
      'Machine users without 2FA also get removed. Move automation to GitHub Apps first.',
    ],
    rollback: 'Removed members can be re-invited; their previous access is restored within 3 months.',
  },
  'dependabot-critical': {
    autoFix: () => manual('Dependency upgrades must pass the test suite and be deployed. Veyra opens the change, a human ships it.'),
    actions: () => [],
    scripts: (f, a) => [{
      label: 'GitHub CLI',
      language: 'bash',
      code: [
        `gh api "repos/${q(orgOf(a))}/${q(f.resource.repo)}/dependabot/alerts?severity=critical&state=open" \\`,
        "  --jq '.[] | [.number, .dependency.package.name, .security_advisory.cve_id] | @tsv'",
        '',
        '# Review and merge the Dependabot pull requests once CI is green',
        `gh pr list -R ${q(orgOf(a))}/${q(f.resource.repo)} --author app/dependabot`,
        `gh pr merge <number> -R ${q(orgOf(a))}/${q(f.resource.repo)} --squash`,
      ].join('\n'),
    }],
    sideEffects: [
      'Major-version bumps can contain breaking API changes; run the full test suite before deploying.',
      'Lockfile changes can pull in new transitive dependencies; review the diff.',
    ],
    rollback: 'Revert the merge commit and redeploy the previous build.',
  },
  'outside-collaborator-admin': {
    autoFix: () => auto('administration:write (collaborators)'),
    actions: (f, a) => [`PUT /repos/${orgOf(a)}/${f.resource.repo}/collaborators/${f.resource.user} {"permission":"push"}`],
    scripts: (f, a) => [{
      label: 'GitHub CLI',
      language: 'bash',
      code: [
        '# Downgrade from admin to write',
        `gh api -X PUT repos/${q(orgOf(a))}/${q(f.resource.repo)}/collaborators/${q(f.resource.user)} -f permission=push`,
        '',
        '# Or remove entirely if the engagement has ended',
        `gh api -X DELETE repos/${q(orgOf(a))}/${q(f.resource.repo)}/collaborators/${q(f.resource.user)}`,
      ].join('\n'),
    }],
    sideEffects: [
      'The collaborator can no longer change settings, webhooks or deploy keys; tasks they own may stall.',
    ],
    rollback: `Re-grant admin: gh api -X PUT repos/<org>/<repo>/collaborators/<user> -f permission=admin`,
  },
  'public-repo-internal': {
    autoFix: () => auto('administration:write (repository visibility)'),
    actions: (f, a) => [`PATCH /repos/${orgOf(a)}/${f.resource.repo} {"visibility":"private"}`],
    scripts: (f, a) => [{
      label: 'GitHub CLI',
      language: 'bash',
      code: `gh repo edit ${q(orgOf(a))}/${q(f.resource.repo)} --visibility private --accept-visibility-change-consequences`,
    }],
    sideEffects: [
      'Existing public forks stay public and are detached; the exposed history cannot be recalled.',
      'Stars and watchers are lost; GitHub Pages sites and anonymous clones (e.g. in CI or Dockerfiles) break.',
    ],
    rollback: 'gh repo edit <org>/<repo> --visibility public --accept-visibility-change-consequences',
  },
  'deploy-key-write': {
    autoFix: () => auto('administration:write (deploy keys)'),
    actions: (f, a) => [`DELETE /repos/${orgOf(a)}/${f.resource.repo}/keys/{key_id}`],
    scripts: (f, a) => [{
      label: 'GitHub CLI',
      language: 'bash',
      code: [
        `gh repo deploy-key list -R ${q(orgOf(a))}/${q(f.resource.repo)}`,
        `gh repo deploy-key delete <key-id> -R ${q(orgOf(a))}/${q(f.resource.repo)}`,
        '',
        '# Replace with a read-only key if the deployment only pulls',
        `gh repo deploy-key add deploy_ro.pub -R ${q(orgOf(a))}/${q(f.resource.repo)} --title "deploy (read-only)"`,
      ].join('\n'),
    }],
    sideEffects: [
      'Any deployment or mirror job authenticating with this key fails until it uses the replacement.',
    ],
    rollback: 'Add the original public key back as a deploy key with write access.',
  },
  'external-email-member': {
    autoFix: () => manual('Only the member can add and verify a corporate email address on their account.'),
    actions: () => [],
    scripts: (f, a) => [{
      label: 'GitHub CLI',
      language: 'bash',
      code: [
        '# Enforce SAML SSO so access is tied to your identity provider',
        `# Settings > Authentication security > Enable SAML authentication (${q(orgOf(a))})`,
        `gh api orgs/${q(orgOf(a))}/members?role=admin --jq '.[].login'`,
      ].join('\n'),
    }],
    sideEffects: ['Enforcing SSO removes members who have not linked an identity.'],
    rollback: 'Disable SAML enforcement in organization settings.',
  },

  // --------------------------------------------------------------------- AWS
  's3-public-bucket': {
    autoFix: () => auto('s3:PutBucketPublicAccessBlock, s3:PutBucketPolicy'),
    actions: (f) => [
      `s3:PutPublicAccessBlock bucket=${f.resource.name} (all four settings = true)`,
      `s3:PutBucketPolicy bucket=${f.resource.name} (remove Principal "*")`,
    ],
    scripts: (f) => [
      {
        label: 'AWS CLI',
        language: 'bash',
        code: [
          `aws s3api put-public-access-block --bucket ${q(f.resource.name)} \\`,
          '  --public-access-block-configuration \\',
          '  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true',
          '',
          '# Back up the policy, remove the Principal "*" statement, re-apply',
          `aws s3api get-bucket-policy --bucket ${q(f.resource.name)} --query Policy --output text > policy.backup.json`,
          `aws s3api put-bucket-policy --bucket ${q(f.resource.name)} --policy file://policy.fixed.json`,
          '',
          '# Guardrail for every bucket in the account',
          'aws s3control put-public-access-block --account-id "$(aws sts get-caller-identity --query Account --output text)" \\',
          '  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true',
        ].join('\n'),
      },
      {
        label: 'Terraform',
        language: 'hcl',
        code: [
          `resource "aws_s3_bucket_public_access_block" "${q(f.resource.name).replace(/[^\w]/g, '_')}" {`,
          `  bucket                  = "${q(f.resource.name)}"`,
          '  block_public_acls       = true',
          '  ignore_public_acls      = true',
          '  block_public_policy     = true',
          '  restrict_public_buckets = true',
          '}',
        ].join('\n'),
      },
    ],
    sideEffects: [
      'Websites, CDNs or partners reading objects anonymously get 403 errors. Serve them through CloudFront with origin access control instead.',
      'Pre-signed URLs keep working; public object ACLs stop working.',
    ],
    rollback: 'aws s3api delete-public-access-block --bucket <bucket> and restore policy.backup.json',
  },
  'root-no-mfa': {
    autoFix: () => manual('MFA for the root user can only be registered by someone signed in as root with the physical device.'),
    actions: () => [],
    scripts: () => [{
      label: 'AWS CLI',
      language: 'bash',
      code: [
        '# Verify (run with an admin role, not root)',
        "aws iam get-account-summary --query 'SummaryMap.[AccountMFAEnabled,AccountAccessKeysPresent]'",
        '',
        '# As root, in the console: Security credentials > Assign MFA device (passkey or hardware key)',
        '# Then delete the root access key from the same page and alert on root usage:',
        'aws cloudwatch put-metric-alarm --alarm-name root-account-usage --namespace CloudTrailMetrics \\',
        '  --metric-name RootAccountUsage --statistic Sum --period 300 --threshold 1 \\',
        '  --comparison-operator GreaterThanOrEqualToThreshold --evaluation-periods 1 --alarm-actions <sns-topic-arn>',
      ].join('\n'),
    }],
    sideEffects: [
      'Anything still using the root access key breaks when it is deleted. Check CloudTrail for its last use first.',
      'Store the MFA device in a break-glass process; losing it means an AWS support recovery.',
    ],
    rollback: 'Not applicable: MFA and key deletion should not be reverted.',
  },
  'sg-open-ssh': {
    autoFix: () => auto('ec2:RevokeSecurityGroupIngress'),
    actions: (f) => [`ec2:RevokeSecurityGroupIngress group=${f.resource.id} tcp/${f.resource.port} 0.0.0.0/0 region=${f.resource.location}`],
    scripts: (f) => [
      {
        label: 'AWS CLI',
        language: 'bash',
        code: [
          `aws ec2 revoke-security-group-ingress --region ${q(f.resource.location)} \\`,
          `  --group-id ${q(f.resource.id)} --protocol tcp --port ${Number(f.resource.port) || 22} --cidr 0.0.0.0/0`,
          '',
          '# Administrative access without open ports',
          'aws ssm start-session --target <instance-id>',
        ].join('\n'),
      },
      {
        label: 'Terraform',
        language: 'hcl',
        code: [
          '# Remove the 0.0.0.0/0 ingress block and allow only your VPN range',
          'resource "aws_vpc_security_group_ingress_rule" "admin_from_vpn" {',
          `  security_group_id = "${q(f.resource.id)}"`,
          '  cidr_ipv4         = "10.20.0.0/16" # VPN / bastion range',
          '  ip_protocol       = "tcp"',
          `  from_port         = ${Number(f.resource.port) || 22}`,
          `  to_port           = ${Number(f.resource.port) || 22}`,
          '}',
        ].join('\n'),
      },
    ],
    sideEffects: (f) => [
      `Open ${f.resource.port === 3389 ? 'RDP' : 'SSH'} sessions to ${f.resource.instances} instance(s) are dropped, and automation that connects over the internet (Ansible, CI deploys) stops working.`,
      'Confirm the SSM agent is running on the instances before removing the rule, or you may lose access entirely.',
    ],
    rollback: 'aws ec2 authorize-security-group-ingress --group-id <sg> --protocol tcp --port <port> --cidr <your-ip>/32',
  },
  'cloudtrail-disabled': {
    autoFix: () => auto('cloudtrail:CreateTrail, cloudtrail:StartLogging'),
    actions: (f) => ['cloudtrail:CreateTrail name=org-trail multiRegion=true logFileValidation=true', `cloudtrail:StartLogging name=org-trail (covers ${f.resource.location})`],
    scripts: (f) => [
      {
        label: 'AWS CLI',
        language: 'bash',
        code: [
          'aws cloudtrail create-trail --name org-trail --s3-bucket-name <log-archive-bucket> \\',
          '  --is-multi-region-trail --enable-log-file-validation',
          'aws cloudtrail start-logging --name org-trail',
          `aws cloudtrail get-trail-status --name org-trail --region ${q(f.resource.location)}`,
        ].join('\n'),
      },
      {
        label: 'Terraform',
        language: 'hcl',
        code: [
          'resource "aws_cloudtrail" "org" {',
          '  name                          = "org-trail"',
          '  s3_bucket_name                = "<log-archive-bucket>"',
          '  is_multi_region_trail         = true',
          '  include_global_service_events = true',
          '  enable_log_file_validation    = true',
          '}',
        ].join('\n'),
      },
    ],
    sideEffects: [
      'The log bucket policy must allow cloudtrail.amazonaws.com to write, or the trail fails to start.',
      'Adds S3 storage cost for logs (management events: the first copy is free).',
    ],
    rollback: 'aws cloudtrail stop-logging --name org-trail',
  },
  'stale-access-keys': {
    autoFix: () => auto('iam:UpdateAccessKey'),
    actions: (f) => [`iam:UpdateAccessKey user=${f.resource.name} status=Inactive (reversible for 7 days)`],
    scripts: (f) => [{
      label: 'AWS CLI',
      language: 'bash',
      code: [
        `aws iam list-access-keys --user-name ${q(f.resource.name)}`,
        `aws iam get-access-key-last-used --access-key-id <AKIA...>`,
        '',
        '# Rotate: create the new key, update consumers, then deactivate the old one',
        `aws iam create-access-key --user-name ${q(f.resource.name)}`,
        `aws iam update-access-key --user-name ${q(f.resource.name)} --access-key-id <old-key-id> --status Inactive`,
        '# After a week with no errors:',
        `aws iam delete-access-key --user-name ${q(f.resource.name)} --access-key-id <old-key-id>`,
      ].join('\n'),
    }],
    sideEffects: (f) => [
      `Whatever authenticates as ${f.resource.name} with this key (CI pipelines, cron jobs, laptops) fails immediately after deactivation.`,
      'Check get-access-key-last-used to find the consumer before you act.',
    ],
    rollback: 'aws iam update-access-key --user-name <user> --access-key-id <key> --status Active',
  },
  'rds-public': {
    autoFix: () => auto('rds:ModifyDBInstance'),
    actions: (f) => [`rds:ModifyDBInstance id=${f.resource.name} PubliclyAccessible=false ApplyImmediately=true`],
    scripts: (f) => [
      {
        label: 'AWS CLI',
        language: 'bash',
        code: `aws rds modify-db-instance --db-instance-identifier ${q(f.resource.name)} --no-publicly-accessible --apply-immediately`,
      },
      {
        label: 'Terraform',
        language: 'hcl',
        code: [
          `resource "aws_db_instance" "${q(f.resource.name).replace(/[^\w]/g, '_')}" {`,
          '  # ...existing configuration...',
          '  publicly_accessible = false',
          '}',
        ].join('\n'),
      },
    ],
    sideEffects: [
      'Clients outside the VPC (BI tools, developer laptops, external ETL) lose their connection; give them a VPN or bastion path first.',
      'The endpoint DNS name resolves to a private IP after the change; cached connections may need a restart.',
    ],
    rollback: 'aws rds modify-db-instance --db-instance-identifier <id> --publicly-accessible --apply-immediately',
  },
  'ebs-unencrypted': {
    autoFix: () => manual('Existing volumes can only be encrypted by re-creating them from encrypted snapshots during a maintenance window.'),
    actions: () => [],
    scripts: () => [{
      label: 'AWS CLI',
      language: 'bash',
      code: [
        '# Encrypt everything new, in every region',
        'for region in $(aws ec2 describe-regions --query "Regions[].RegionName" --output text); do',
        '  aws ec2 enable-ebs-encryption-by-default --region "$region"',
        'done',
        '',
        '# Per existing volume (maintenance window):',
        'aws ec2 create-snapshot --volume-id <vol-id>',
        'aws ec2 copy-snapshot --source-region <region> --source-snapshot-id <snap-id> --encrypted',
        'aws ec2 create-volume --snapshot-id <encrypted-snap-id> --availability-zone <az>',
      ].join('\n'),
    }],
    sideEffects: ['Swapping a volume requires stopping the instance; plan downtime.'],
    rollback: 'aws ec2 disable-ebs-encryption-by-default --region <region>',
  },

  // -------------------------------------------------------- Google Workspace
  'unverified-external-admin': {
    autoFix: () => auto('admin.directory.rolemanagement (role assignments: delete)'),
    actions: (f) => [`DELETE admin/directory/v1/customer/my_customer/roleassignments/{id} user=${f.resource.email} role=${f.resource.role}`],
    scripts: (f) => [{
      label: 'Admin SDK (curl)',
      language: 'bash',
      code: [
        'TOKEN=$(gcloud auth print-access-token)',
        '',
        '# Find the role assignment held by the external account',
        'curl -s -H "Authorization: Bearer $TOKEN" \\',
        `  "https://admin.googleapis.com/admin/directory/v1/customer/my_customer/roleassignments?userKey=${q(f.resource.email)}"`,
        '',
        '# Revoke it',
        'curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \\',
        '  "https://admin.googleapis.com/admin/directory/v1/customer/my_customer/roleassignments/<roleAssignmentId>"',
      ].join('\n'),
    }],
    sideEffects: [
      'Integrations or scripts running as this admin stop working immediately.',
      'Keep at least two super admins in your own domain so you are not locked out.',
    ],
    rollback: 'Re-create the role assignment in Admin console > Account > Admin roles (only after verifying the identity).',
  },
  'admins-without-2sv': {
    autoFix: () => manual('Enforcing 2-Step Verification locks out admins who have not enrolled yet. Give them a short enrollment window first.'),
    actions: () => [],
    scripts: (f, a) => [{
      label: 'Admin SDK (curl)',
      language: 'bash',
      code: [
        'TOKEN=$(gcloud auth print-access-token)',
        'curl -s -H "Authorization: Bearer $TOKEN" \\',
        `  "https://admin.googleapis.com/admin/directory/v1/users?domain=${q(domainOf(a))}&query=isAdmin=true%20isEnrolledIn2Sv=false"`,
        '',
        '# Then: Admin console > Security > 2-Step Verification > Enforcement: On (admin OU)',
      ].join('\n'),
    }],
    sideEffects: ['Admins who have not enrolled cannot sign in after enforcement until they complete 2SV setup.'],
    rollback: 'Set enforcement back to Off for the admin organizational unit.',
  },
  'drive-public-sensitive': {
    autoFix: () => auto('drive (permissions.delete)'),
    actions: (f) => [`DELETE drive/v3/files/{fileId}/permissions/anyoneWithLink file="${f.resource.name}"`],
    scripts: (f) => [{
      label: 'Drive API (curl)',
      language: 'bash',
      code: [
        `# "${String(f.resource.name).replace(/[^\w .,()&-]/g, '')}" (owner: ${q(f.resource.owner)})`,
        'TOKEN=$(gcloud auth print-access-token)',
        'curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \\',
        '  "https://www.googleapis.com/drive/v3/files/<FILE_ID>/permissions/anyoneWithLink?supportsAllDrives=true"',
      ].join('\n'),
    }],
    sideEffects: [
      'External partners using the link lose access; share with them by name instead.',
      'Documents embedded in websites or other docs stop rendering for anonymous viewers.',
    ],
    rollback: 'Re-share with "Anyone with the link" from the file\'s Share dialog.',
  },
  'risky-oauth-app': {
    autoFix: () => auto('admin.directory.user.security (tokens: delete)'),
    actions: (f) => [`DELETE admin/directory/v1/users/{user}/tokens/{clientId} app="${f.resource.name}" users=${f.resource.users}`, 'Block app in API controls'],
    scripts: (f) => [{
      label: 'Admin SDK (curl)',
      language: 'bash',
      code: [
        'TOKEN=$(gcloud auth print-access-token)',
        `# Revoke "${String(f.resource.name).replace(/[^\w .-]/g, '')}" for every user who granted it`,
        'for user in $(cat users-with-app.txt); do',
        '  curl -s -X DELETE -H "Authorization: Bearer $TOKEN" \\',
        '    "https://admin.googleapis.com/admin/directory/v1/users/$user/tokens/<CLIENT_ID>"',
        'done',
        '# Then: Admin console > Security > API controls > App access control > Block',
      ].join('\n'),
    }],
    sideEffects: (f) => [
      `The ${f.resource.users} users relying on "${f.resource.name}" lose its functionality; check whether a team depends on it.`,
      'Users may try a different unvetted app instead. Publish an approved alternative.',
    ],
    rollback: 'Unblock the app in API controls; users must re-consent.',
  },
  'auto-forwarding': {
    autoFix: () => auto('gmail.settings.sharing (autoForwarding: update)'),
    actions: (f) => [`PUT gmail/v1/users/${f.resource.name}/settings/autoForwarding {"enabled":false}`],
    scripts: (f) => [{
      label: 'Gmail API (curl)',
      language: 'bash',
      code: [
        '# Requires a domain-wide delegated token for the user',
        'curl -s -X PUT -H "Authorization: Bearer $USER_TOKEN" -H "Content-Type: application/json" \\',
        `  "https://gmail.googleapis.com/gmail/v1/users/${q(f.resource.name)}/settings/autoForwarding" \\`,
        '  -d \'{"enabled": false}\'',
        '# Then: Admin console > Apps > Gmail > End user access > Automatic forwarding: Off',
      ].join('\n'),
    }],
    sideEffects: [
      'The user stops receiving forwarded mail. Confirm it is not a legitimate arrangement, e.g. during leave.',
      'If this was attacker persistence, also reset the password and review sign-ins.',
    ],
    rollback: 'Re-enable forwarding in the user\'s Gmail settings.',
  },
  'dormant-admin': {
    autoFix: () => auto('admin.directory.user (users: update)'),
    actions: (f) => [`PATCH admin/directory/v1/users/${f.resource.name} {"suspended":true}`],
    scripts: (f) => [{
      label: 'Admin SDK (curl)',
      language: 'bash',
      code: [
        'TOKEN=$(gcloud auth print-access-token)',
        'curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\',
        `  "https://admin.googleapis.com/admin/directory/v1/users/${q(f.resource.name)}" -d '{"suspended": true}'`,
      ].join('\n'),
    }],
    sideEffects: ['If the account is secretly used by an integration, that integration stops. Data is retained while suspended.'],
    rollback: 'PATCH the user with {"suspended": false}.',
  },

  // ----------------------------------------------------------- Microsoft 365
  'mfa-not-enforced': {
    autoFix: () => manual('Tenant-wide MFA needs a report-only soak period and break-glass exclusions to avoid locking users out.'),
    actions: () => [],
    scripts: () => [{
      label: 'Microsoft Graph PowerShell',
      language: 'powershell',
      code: [
        'Connect-MgGraph -Scopes "Policy.ReadWrite.ConditionalAccess"',
        '',
        '$policy = @{',
        '  displayName = "Require MFA for all users"',
        '  state       = "enabledForReportingButNotEnforced"   # switch to "enabled" after review',
        '  conditions  = @{',
        '    users        = @{ includeUsers = @("All"); excludeUsers = @("<break-glass-1-id>", "<break-glass-2-id>") }',
        '    applications = @{ includeApplications = @("All") }',
        '  }',
        '  grantControls = @{ operator = "OR"; builtInControls = @("mfa") }',
        '}',
        'New-MgIdentityConditionalAccessPolicy -BodyParameter $policy',
      ].join('\n'),
    }],
    sideEffects: [
      'Users without a registered MFA method are prompted to register on next sign-in; expect helpdesk tickets.',
      'Service accounts using passwords break; move them to workload identities.',
    ],
    rollback: 'Set the policy state to "disabled".',
  },
  'legacy-auth': {
    autoFix: () => auto('Policy.ReadWrite.ConditionalAccess'),
    actions: () => ['POST /identity/conditionalAccess/policies "Block legacy authentication" (clientAppTypes: exchangeActiveSync, other)'],
    scripts: () => [{
      label: 'Microsoft Graph PowerShell',
      language: 'powershell',
      code: [
        'Connect-MgGraph -Scopes "Policy.ReadWrite.ConditionalAccess"',
        '',
        'New-MgIdentityConditionalAccessPolicy -BodyParameter @{',
        '  displayName   = "Block legacy authentication"',
        '  state         = "enabled"',
        '  conditions    = @{',
        '    users          = @{ includeUsers = @("All") }',
        '    applications   = @{ includeApplications = @("All") }',
        '    clientAppTypes = @("exchangeActiveSync", "other")',
        '  }',
        '  grantControls = @{ operator = "OR"; builtInControls = @("block") }',
        '}',
      ].join('\n'),
    }],
    sideEffects: [
      'Old mail clients, multifunction printers and scripts using SMTP AUTH or IMAP stop authenticating.',
      'Check the sign-in logs filtered on "Client app: other clients" for active users first.',
    ],
    rollback: 'Set the "Block legacy authentication" policy state to "disabled".',
  },
  'external-forwarding-rule': {
    autoFix: () => auto('Exchange.ManageAsApp, User.RevokeSessions.All'),
    actions: (f) => [
      `Export-InboxRule mailbox=${f.resource.name} (evidence)`,
      `Remove-InboxRule mailbox=${f.resource.name} name="${f.resource.ruleName}"`,
      `Revoke-MgUserSignInSession user=${f.resource.name}`,
    ],
    scripts: (f) => [{
      label: 'Exchange Online PowerShell',
      language: 'powershell',
      code: [
        'Connect-ExchangeOnline',
        `$rules = Get-InboxRule -Mailbox "${q(f.resource.name)}" -IncludeHidden`,
        '$rules | Export-Clixml inbox-rules-evidence.xml   # keep for the investigation',
        `$rules | Where-Object { $_.ForwardTo -or $_.RedirectTo -or $_.ForwardAsAttachmentTo } | Remove-InboxRule -Confirm:$false`,
        '',
        'Connect-MgGraph -Scopes "User.RevokeSessions.All"',
        `Revoke-MgUserSignInSession -UserId "${q(f.resource.name)}"`,
      ].join('\n'),
    }],
    sideEffects: [
      'The user is signed out on every device and must sign in again.',
      'Treat this as a possible compromise: reset the password and re-register MFA, not just the rule.',
    ],
    rollback: 'Import the exported rule definition with New-InboxRule (not recommended).',
  },
  'sharepoint-anyone-links': {
    autoFix: () => auto('Sites.FullControl.All (permissions: delete)'),
    actions: (f) => [`DELETE /drives/{drive-id}/items/{item-id}/permissions/{anonymous-link-id} file="${f.resource.name}" site=${f.resource.site}`],
    scripts: () => [{
      label: 'Microsoft Graph PowerShell',
      language: 'powershell',
      code: [
        'Connect-MgGraph -Scopes "Sites.ReadWrite.All"',
        '$perms = Get-MgDriveItemPermission -DriveId <drive-id> -DriveItemId <item-id>',
        '$perms | Where-Object { $_.Link.Scope -eq "anonymous" } | ForEach-Object {',
        '  Remove-MgDriveItemPermission -DriveId <drive-id> -DriveItemId <item-id> -PermissionId $_.Id',
        '}',
        '',
        '# Tenant guardrail',
        'Set-SPOTenant -SharingCapability ExistingExternalUserSharingOnly',
      ].join('\n'),
    }],
    sideEffects: [
      'External recipients of the link lose access; re-share with named guests if needed.',
      'Changing the tenant sharing capability affects every site, not just this file.',
    ],
    rollback: 'Create a new sharing link from the file\'s Share dialog.',
  },
  'too-many-global-admins': {
    autoFix: () => manual('Choosing which administrators keep the role is a business decision.'),
    actions: () => [],
    scripts: () => [{
      label: 'Microsoft Graph PowerShell',
      language: 'powershell',
      code: [
        'Connect-MgGraph -Scopes "RoleManagement.Read.Directory"',
        '# Global Administrator role template',
        'Get-MgDirectoryRoleMember -DirectoryRoleId (Get-MgDirectoryRole -Filter "roleTemplateId eq \'62e90394-69f5-4237-9190-012177145e10\'").Id |',
        '  ForEach-Object { Get-MgUser -UserId $_.Id | Select-Object DisplayName, UserPrincipalName }',
      ].join('\n'),
    }],
    sideEffects: ['Admins moved to narrower roles may lose access to settings they use; map their tasks to roles first.'],
    rollback: 'Re-assign the Global Administrator role (preferably as PIM-eligible, not permanent).',
  },
  'audit-disabled': {
    autoFix: () => auto('Exchange.ManageAsApp'),
    actions: () => ['Set-OrganizationConfig -AuditDisabled $false', 'Set-MailboxAuditBypassAssociation -AuditBypassEnabled $false (all bypassed mailboxes)'],
    scripts: () => [{
      label: 'Exchange Online PowerShell',
      language: 'powershell',
      code: [
        'Connect-ExchangeOnline',
        'Set-OrganizationConfig -AuditDisabled $false',
        'Get-MailboxAuditBypassAssociation -ResultSize Unlimited | Where-Object AuditBypassEnabled |',
        '  ForEach-Object { Set-MailboxAuditBypassAssociation -Identity $_.Identity -AuditBypassEnabled $false }',
      ].join('\n'),
    }],
    sideEffects: ['Audit log volume grows; check retention licensing (Audit Standard: 180 days).'],
    rollback: 'Set-MailboxAuditBypassAssociation -Identity <mailbox> -AuditBypassEnabled $true',
  },

  // ------------------------------------------------------------------- Azure
  'storage-public-blob': {
    autoFix: () => auto('Microsoft.Storage/storageAccounts/write'),
    actions: (f) => [`PATCH storageAccounts/${f.resource.name} allowBlobPublicAccess=false`],
    scripts: (f, a) => [
      {
        label: 'Azure CLI',
        language: 'bash',
        code: [
          `az account set --subscription ${q(subOf(a))}`,
          `az storage account update --name ${q(f.resource.name)} --resource-group <rg> --allow-blob-public-access false`,
        ].join('\n'),
      },
      {
        label: 'Terraform',
        language: 'hcl',
        code: [
          `resource "azurerm_storage_account" "${q(f.resource.name)}" {`,
          '  # ...existing configuration...',
          '  allow_nested_items_to_be_public = false',
          '}',
        ].join('\n'),
      },
    ],
    sideEffects: (f) => [
      `Anonymous reads of container "${f.resource.container}" fail; static websites or CDN origins relying on it break.`,
      'Use SAS tokens with short expiry or a private endpoint for legitimate sharing.',
    ],
    rollback: 'az storage account update --name <account> --resource-group <rg> --allow-blob-public-access true',
  },
  'nsg-open-rdp': {
    autoFix: () => auto('Microsoft.Network/networkSecurityGroups/securityRules/delete'),
    actions: (f) => [`DELETE networkSecurityGroups/${f.resource.name}/securityRules/{Any->3389}`],
    scripts: (f, a) => [{
      label: 'Azure CLI',
      language: 'bash',
      code: [
        `az account set --subscription ${q(subOf(a))}`,
        `az network nsg rule list --nsg-name ${q(f.resource.name)} --resource-group <rg> \\`,
        `  --query "[?destinationPortRange=='3389' && sourceAddressPrefix=='*'].name" -o tsv`,
        `az network nsg rule delete --nsg-name ${q(f.resource.name)} --resource-group <rg> --name <rule-name>`,
        '',
        '# Administrative access without open ports',
        'az network bastion create --name bastion --resource-group <rg> --vnet-name <vnet> --public-ip-address <pip>',
      ].join('\n'),
    }],
    sideEffects: [
      'Active RDP sessions drop. Set up Azure Bastion or just-in-time access before removing the rule.',
    ],
    rollback: 'Recreate the rule restricted to your office or VPN IP range, not "Any".',
  },
  'guest-owner': {
    autoFix: () => auto('Microsoft.Authorization/roleAssignments/delete'),
    actions: (f, a) => [`DELETE roleAssignments assignee=${f.resource.email} role=Owner scope=/subscriptions/${subOf(a)}`],
    scripts: (f, a) => [{
      label: 'Azure CLI',
      language: 'bash',
      code: [
        `az role assignment delete --assignee "${q(f.resource.email)}" --role Owner --scope /subscriptions/${q(subOf(a))}`,
        '',
        '# Grant only what is needed, scoped to one resource group',
        `az role assignment create --assignee "${q(f.resource.email)}" --role Contributor \\`,
        `  --scope /subscriptions/${q(subOf(a))}/resourceGroups/<rg>`,
      ].join('\n'),
    }],
    sideEffects: [
      'Work the guest is doing (e.g. a vendor managing infrastructure) stops until a narrower role is granted.',
    ],
    rollback: `az role assignment create --assignee <guest> --role Owner --scope /subscriptions/<sub>`,
  },
  'sql-firewall-any': {
    autoFix: () => auto('Microsoft.Sql/servers/firewallRules/delete'),
    actions: (f) => [`DELETE servers/${f.resource.name}/firewallRules/{0.0.0.0-255.255.255.255}`],
    scripts: (f) => [{
      label: 'Azure CLI',
      language: 'bash',
      code: [
        `az sql server firewall-rule list --server ${q(f.resource.name)} --resource-group <rg> -o table`,
        `az sql server firewall-rule delete --server ${q(f.resource.name)} --resource-group <rg> --name <rule-name>`,
        `az sql server update --name ${q(f.resource.name)} --resource-group <rg> --enable-public-network false`,
      ].join('\n'),
    }],
    sideEffects: [
      'Applications and tools connecting from outside your network lose access. Add a private endpoint or specific IP rules first.',
    ],
    rollback: 'az sql server firewall-rule create --server <server> --resource-group <rg> --name <name> --start-ip-address <ip> --end-ip-address <ip>',
  },
  'keyvault-no-purge': {
    autoFix: () => auto('Microsoft.KeyVault/vaults/write'),
    actions: (f) => [`PATCH vaults/${f.resource.name} enablePurgeProtection=true`],
    scripts: (f) => [{
      label: 'Azure CLI',
      language: 'bash',
      code: `az keyvault update --name ${q(f.resource.name)} --enable-purge-protection true`,
    }],
    sideEffects: [
      'Purge protection is irreversible: it cannot be turned off again for this vault.',
      'Deleted vaults and keys stay in a soft-deleted state for the retention period, and their names stay reserved.',
    ],
    rollback: 'None: purge protection cannot be disabled once enabled.',
  },
  'defender-off': {
    autoFix: () => auto('Microsoft.Security/pricings/write'),
    actions: (f) => f.resource.plans.map((p) => `PUT pricings/${DEFENDER_PLANS[p] ?? p} tier=Standard`),
    scripts: (f, a) => [{
      label: 'Azure CLI',
      language: 'bash',
      code: [
        `az account set --subscription ${q(subOf(a))}`,
        ...f.resource.plans.map((p) => `az security pricing create --name ${DEFENDER_PLANS[p] ?? q(p)} --tier standard`),
      ].join('\n'),
    }],
    sideEffects: ['Each Defender plan is billed per protected resource; review the cost estimate before enabling.'],
    rollback: 'az security pricing create --name <plan> --tier free',
  },

  // ------------------------------------------------------------------- Slack
  'public-file-links': {
    autoFix: () => auto('files:write (files.revokePublicURL), admin settings'),
    actions: (f) => [`files.revokePublicURL x${f.resource.count}`, 'Disable workspace setting "Public file sharing"'],
    scripts: () => [{
      label: 'Slack Web API',
      language: 'bash',
      code: [
        '# Revoke each public link (file IDs from the Veyra evidence export)',
        'while read -r file_id; do',
        '  curl -s -X POST https://slack.com/api/files.revokePublicURL \\',
        '    -H "Authorization: Bearer $SLACK_ADMIN_TOKEN" -d "file=$file_id"',
        'done < public-file-ids.txt',
        '',
        '# Then: Workspace settings > Permissions > Public file sharing: Off',
      ].join('\n'),
    }],
    sideEffects: [
      'Anyone outside Slack using these links (customers, partners, docs) gets "file not found".',
      'Members can no longer create public links; external sharing has to use Slack Connect or a governed file store.',
    ],
    rollback: 'Re-enable public file sharing and have owners re-create the links they still need.',
  },
  'external-sensitive-channel': {
    autoFix: () => manual('Disconnecting a partner from a shared channel is a business decision for the channel owner.'),
    actions: () => [],
    scripts: (f) => [{
      label: 'Slack Admin API',
      language: 'bash',
      code: [
        `# #${q(f.resource.name)} shared with ${String(f.resource.partner).replace(/[^\w .-]/g, '')}`,
        'curl -s -X POST https://slack.com/api/admin.conversations.disconnectShared \\',
        '  -H "Authorization: Bearer $SLACK_ADMIN_TOKEN" -d "channel_id=<CHANNEL_ID>"',
      ].join('\n'),
    }],
    sideEffects: ['The partner loses the channel and its history immediately; agree on an alternative channel first.'],
    rollback: 'Send a new Slack Connect invitation to the partner organization.',
  },
  'admin-scoped-app': {
    autoFix: () => auto('admin.apps:write (admin.apps.restrict)'),
    actions: (f) => [`admin.apps.restrict app="${f.resource.name}"`],
    scripts: (f) => [{
      label: 'Slack Admin API',
      language: 'bash',
      code: [
        `# Restrict "${String(f.resource.name).replace(/[^\w .-]/g, '')}" (installed by ${q(f.resource.installer)})`,
        'curl -s -X POST https://slack.com/api/admin.apps.restrict \\',
        '  -H "Authorization: Bearer $SLACK_ADMIN_TOKEN" -d "app_id=<APP_ID>" -d "team_id=<TEAM_ID>"',
        '',
        '# Then: Settings > Manage apps > Require app approval',
      ].join('\n'),
    }],
    sideEffects: ['Workflows and channels that depend on the app stop working until it is reinstalled with narrower scopes.'],
    rollback: 'Approve the app again with admin.apps.approve.',
  },
  'no-2fa': {
    autoFix: () => manual('Requiring 2FA or SSO signs out every member who has not enrolled; announce it before enforcing.'),
    actions: () => [],
    scripts: (f, a) => [{
      label: 'Steps',
      language: 'text',
      code: [
        `${workspaceOf(a)}.slack.com/admin/auth`,
        '1. Configure SAML SSO with your identity provider (preferred), or',
        '2. Authentication > Two-factor authentication > "Require 2FA for your workspace"',
        '3. Announce in #general 7 days before enforcing',
      ].join('\n'),
    }],
    sideEffects: ['Members without 2FA are signed out and cannot rejoin until they enroll.'],
    rollback: 'Turn off the 2FA requirement in workspace authentication settings.',
  },
  'guest-no-expiry': {
    autoFix: () => auto('admin.users:write (admin.users.setExpiration)'),
    actions: (f) => [`admin.users.setExpiration x${f.resource.count} guests expiration=+30d`],
    scripts: () => [{
      label: 'Slack Admin API',
      language: 'bash',
      code: [
        'EXPIRES=$(date -d "+30 days" +%s)',
        'while read -r user_id; do',
        '  curl -s -X POST https://slack.com/api/admin.users.setExpiration \\',
        '    -H "Authorization: Bearer $SLACK_ADMIN_TOKEN" -d "user_id=$user_id" -d "expiration_ts=$EXPIRES"',
        'done < guest-ids.txt',
      ].join('\n'),
    }],
    sideEffects: ['Guests on active engagements lose access on the expiry date unless an owner extends it.'],
    rollback: 'Call admin.users.setExpiration with a later date, or remove the expiration in the admin dashboard.',
  },
  'unlimited-retention': {
    autoFix: () => manual('Retention periods must match legal hold and regulatory requirements; legal has to sign off.'),
    actions: () => [],
    scripts: (f, a) => [{
      label: 'Steps',
      language: 'text',
      code: [
        `${workspaceOf(a)}.slack.com/admin/settings#data_retention`,
        '1. Agree a retention period with legal (e.g. 2 years for messages, 1 year for files)',
        '2. Set "Messages and files" retention, with exceptions for legal hold channels',
      ].join('\n'),
    }],
    sideEffects: ['Messages and files older than the retention period are permanently deleted.'],
    rollback: 'Deleted content cannot be restored; set retention back to "Keep everything" to stop further deletion.',
  },
};

const DEFENDER_PLANS = {
  Servers: 'VirtualMachines',
  Storage: 'StorageAccounts',
  'Key Vault': 'KeyVaults',
  SQL: 'SqlServers',
  Containers: 'Containers',
};

const GENERIC = {
  autoFix: () => manual('No automated playbook exists for this check yet.'),
  actions: () => [],
  scripts: (f) => [{
    label: 'Steps',
    language: 'text',
    code: (f.remediation ?? []).map((step, i) => `${i + 1}. ${step}`).join('\n'),
  }],
  sideEffects: ['Review the change with the system owner before applying it.'],
  rollback: 'Revert the configuration change manually.',
};

/** Resolve the playbook for a finding. Never throws: unknown checks get a generic playbook. */
export function getPlaybook(finding, account) {
  const definition = PLAYBOOKS[finding?.templateKey] ?? GENERIC;
  const safe = (fn, fallback) => {
    try {
      return fn();
    } catch {
      return fallback;
    }
  };
  return {
    templateKey: finding?.templateKey,
    autoFix: safe(() => definition.autoFix(finding, account), manual('Playbook unavailable.')),
    actions: safe(() => definition.actions(finding, account), []),
    scripts: safe(() => definition.scripts(finding, account), GENERIC.scripts(finding ?? {})),
    sideEffects: safe(
      () => (typeof definition.sideEffects === 'function' ? definition.sideEffects(finding, account) : [...definition.sideEffects]),
      [...GENERIC.sideEffects],
    ),
    rollback: definition.rollback ?? GENERIC.rollback,
  };
}

export const PLAYBOOK_KEYS = Object.keys(PLAYBOOKS);
