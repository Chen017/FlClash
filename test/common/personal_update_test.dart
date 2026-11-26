import 'package:fl_clash/common/app_update.dart';
import 'package:fl_clash/common/package.dart';
import 'package:fl_clash/common/release_version.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';

ReleaseVersion _remote(String tag) => ReleaseVersion.tryParse(tag)!;

void main() {
  final legacyInstalled = PackageInfo(
    appName: 'FlClash',
    packageName: 'io.github.chen017.flclash',
    version: '0.9.3',
    buildNumber: '7',
  );
  final personalInstalled = PackageInfo(
    appName: 'FlClash',
    packageName: 'io.github.chen017.flclash',
    version: '0.9.5-personal',
    buildNumber: '8',
  );

  test('a core-only release updates once without an endless update prompt', () {
    final installed = installedReleaseVersion(
      legacyInstalled.updateVersion,
      builtTag: '',
    );
    expect(_remote('v0.9.3+8'), greaterThan(installed));
    expect(_remote('v0.9.3+7').compareTo(installed), 0);
    expect(_remote('v0.9.3+6'), lessThan(installed));
    expect(_remote('v0.9.4+8'), greaterThan(installed));
  });

  test('personal version tags order cleanly without endless prompts', () {
    final legacy = installedReleaseVersion(
      legacyInstalled.updateVersion,
      builtTag: '',
    );
    final personal = installedReleaseVersion(
      personalInstalled.updateVersion,
      builtTag: '',
    );
    expect(personalInstalled.updateVersion, '0.9.5-personal');
    expect(_remote('v0.9.5-personal'), greaterThan(legacy));
    expect(_remote('v0.9.5-personal').compareTo(personal), 0);
    expect(_remote('v0.9.5-personal.2'), greaterThan(personal));
    expect(
      _remote('v0.9.5-personal.10'),
      greaterThan(_remote('v0.9.5-personal.2')),
    );
    expect(
      _remote('v0.9.6-personal'),
      greaterThan(_remote('v0.9.5-personal.2')),
    );
    expect(
      _remote('v0.9.5-personal'),
      lessThan(_remote('v0.9.5-personal.2')),
    );
  });
}
