import 'package:fl_clash/common/package.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';

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
    version: '0.9.4-personal',
    buildNumber: '8',
  );

  test('a core-only release updates once without an endless update prompt', () {
    expect(compareVersions('0.9.3+8', legacyInstalled.updateVersion), greaterThan(0));
    expect(compareVersions('0.9.3+7', legacyInstalled.updateVersion), 0);
    expect(compareVersions('0.9.3+6', legacyInstalled.updateVersion), lessThan(0));
    expect(compareVersions('0.9.4+8', legacyInstalled.updateVersion), greaterThan(0));
  });

  test('personal version tags order cleanly without endless prompts', () {
    expect(personalInstalled.updateVersion, '0.9.4-personal');
    expect(compareVersions('0.9.4-personal', legacyInstalled.updateVersion), greaterThan(0));
    expect(compareVersions('0.9.4-personal', personalInstalled.updateVersion), 0);
    expect(compareVersions('0.9.4-personal.2', personalInstalled.updateVersion), greaterThan(0));
    expect(compareVersions('0.9.4-personal.10', '0.9.4-personal.2'), greaterThan(0));
    expect(compareVersions('0.9.5-personal', '0.9.4-personal.2'), greaterThan(0));
    expect(compareVersions('0.9.4-personal', '0.9.4-personal.2'), lessThan(0));
  });
}
