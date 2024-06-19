import os
import shutil
import sys
from argparse import ArgumentParser
from . import spawn
from . import generate_manifest
from . import update_mphalport


IDF_VER = '5.2.0'


def get_partition_file_name(otp):
    if 'Running cmake in directory ' in otp:
        build_path = otp.split('Running cmake in directory ', 1)[-1]
    else:
        build_path = otp.split('Running ninja in directory ', 1)[-1]

    build_path = build_path.split('\n', 1)[0]

    target_file = os.path.join(build_path, 'sdkconfig')

    with open(target_file, 'r') as f:
        file = f.read()

    for i, line in enumerate(file.split('\n')):
        if (
            line.startswith('CONFIG_PARTITION_TABLE_CUSTOM_FILENAME') or
            line.startswith('CONFIG_PARTITION_TABLE_FILENAME')
        ):
            return line.split('=', 1)[-1].replace('"', '')


PARTITION_HEADER = '''\
# Name,   Type, SubType, Offset,  Size, Flags
'''

# OTA boards
# ARDUINO_NANO_ESP32
# SIL_WESP32


class Partition:

    def __init__(self, size):
        self.save_file_path = (
            f'{SCRIPT_DIR}/build/partitions.csv'
        )
        self.first_offset = 0x9000
        self.nvs = 0x6000
        self.phy_init = 0x1000

        if size == int(size / 0x1000) * 0x1000:
            self.factory = size
        else:
            self.factory = (int(size / 0x1000) + 1) * 0x1000

        if ota:
            self.otadata = 0x2000
        else:
            self.otadata = 0x0

    def get_app_size(self) -> int:
        return self.factory

    def set_app_size(self, size):
        if int((self.factory + size) / 0x1000) * 0x1000 == self.factory + size:
            self.factory += size
        else:
            self.factory = (int((self.factory + size) / 0x1000) + 1) * 0x1000

    def save(self):
        offset = self.first_offset
        data = [f'nvs,data,nvs,0x{offset:X},0x{self.nvs:X}']
        offset += self.nvs

        if ota:
            data.append(f'otadata,data,ota,0x{offset:X},0x{self.otadata:X}')
            offset += self.otadata

        data.append(f'phy_init,data,phy,0x{offset:X},0x{self.phy_init:X}')
        offset += self.phy_init

        if ota:
            data.append(f'ota_0,app,ota_0,0x{offset:X},0x{self.factory:X}')
            offset += self.factory
            data.append(f'ota_1,app,ota_1,0x{offset:X},0x{self.factory:X}')
            offset += self.factory
        else:
            data.append(f'factory,app,factory,0x{offset:X},0x{self.factory:X}')
            offset += self.factory

        total_size = int((flash_size * (2 ** 20)) / 0x1000) * 0x1000

        vfs = int((total_size - offset) / 0x1000) * 0x1000
        data.append(f'vfs,data,fat,0x{offset:X},0x{vfs:X}')
        offset += vfs

        if offset > total_size:
            raise RuntimeError(
                'There is not enough flash to store the firmware'
            )

        if not os.path.exists(f'{SCRIPT_DIR}/build'):
            os.mkdir(f'{SCRIPT_DIR}/build')

        with open(self.save_file_path, 'w') as f:
            f.write(PARTITION_HEADER)
            f.write('\n'.join(data))
            f.write('\n')


def get_espidf():

    cmd = [
        [
            'git', 'submodule', 'update', '--init',
            f'--jobs {os.cpu_count()}', '--', 'lib/esp-idf'
        ],
        ['cd', 'lib/esp-idf'],
        [
            'git', 'submodule', 'update', '--init',
            f'--jobs {os.cpu_count()}', '--',
            'components/bt/host/nimble/nimble',
            'components/esp_wifi',
            'components/esptool_py/esptool',
            'components/lwip/lwip',
            'components/mbedtls/mbedtls',
            'components/bt/controller/lib_esp32',
            'components/bt/controller/lib_esp32c3_family'
        ]
    ]
    print()
    print(f'collecting ESP-IDF v{IDF_VER}')
    print('this might take a while...')
    result, _ = spawn(cmd, spinner=True)
    if result != 0:
        sys.exit(result)


board_variant = None
board = None
skip_partition_resize = False
partition_size = -1
flash_size = 4
oct_flash = False

DEBUG = False
deploy = False
PORT = None
BAUD = 460800
ccache = False
disable_OTG = True
onboard_mem_speed = 80
flash_mode = 'QIO'
optimize_size = False
ota = False


def common_args(extra_args):
    global DEBUG
    global PORT
    global BAUD
    global deploy
    global ccache
    global skip_partition_resize
    global partition_size
    global flash_size
    global board_variant
    global optimize_size
    global ota

    if board == 'ARDUINO_NANO_ESP32':
        raise RuntimeError('Board is not currently supported')

    if board in (
        'UM_NANOS3', 'ESP32_GENERIC_S3',
        'UM_TINYS3', 'UM_TINYWATCHS3'
    ):
        def_flash_size = 8
    elif board in (
        'UM_FEATHERS2', 'SIL_WESP32',
        'UM_PROS3', 'UM_FEATHERS3',
    ):
        def_flash_size = 16
    else:
        def_flash_size = 4

    esp_argParser = ArgumentParser(prefix_chars='-BPd')
    esp_argParser.add_argument(
        'BAUD',
        dest='baud',
        default=460800,
        type=int,
        action='store'
    )
    esp_argParser.add_argument(
        'PORT',
        dest='port',
        default=None,
        action='store'
    )
    esp_argParser.add_argument(
        'deploy',
        dest='deploy',
        default=False,
        action='store_true'
    )
    esp_argParser.add_argument(
        '--skip-partition-resize',
        dest='skip_partition_resize',
        help='clean the build',
        default=False,
        action='store_true'
    )
    esp_argParser.add_argument(
        '--partition-size',
        dest='partition_size',
        default=-1,
        type=int,
        action='store'
    )
    esp_argParser.add_argument(
        '--optimize-size',
        dest='optimize_size',
        default=False,
        action='store_true'
    )
    esp_argParser.add_argument(
        '--debug',
        dest='debug',
        default=False,
        action='store_true'
    )
    esp_argParser.add_argument(
        '--ccache',
        dest='ccache',
        default=False,
        action='store_true'
    )

    esp_argParser.add_argument(
        '--flash-size',
        dest='flash_size',
        help='flash size',
        choices=(4, 8, 16, 32, 64, 128),
        default=def_flash_size,
        type=int,
        action='store'
    )
    esp_argParser.add_argument(
        '--ota',
        dest='ota',
        default=False,
        action='store_true'
    )

    esp_args, extra_args = esp_argParser.parse_known_args(extra_args)

    BAUD = esp_args.baud
    PORT = esp_args.port
    deploy = esp_args.deploy
    skip_partition_resize = esp_args.skip_partition_resize
    partition_size = esp_args.partition_size
    ccache = esp_args.ccache
    DEBUG = esp_args.debug
    flash_size = esp_args.flash_size
    optimize_size = esp_args.optimize_size
    ota = esp_args.ota

    return extra_args


def esp32_s3_args(extra_args):
    global oct_flash
    global disable_OTG
    global onboard_mem_speed
    global flash_mode
    global board_variant

    esp_argParser = ArgumentParser(prefix_chars='-B')

    esp_argParser.add_argument(
        'BOARD_VARIANT',
        dest='board_variant',
        default='',
        action='store'
    )
    esp_argParser.add_argument(
        '--usb-otg',
        dest='usb_otg',
        default=False,
        action='store_true'
    )
    esp_argParser.add_argument(
        '--octal-flash',
        help='octal spi flash',
        dest='oct_flash',
        action='store_true'
    )
    esp_argParser.add_argument(
        '--onboard-mem-speed',
        dest='onboard_mem_speed',
        choices=[120, 80],
        default=80,
        type=int,
        action='store'
    )
    esp_argParser.add_argument(
        '--flash-mode',
        dest='flash_mode',
        choices=['QIO', 'QOUT', 'DIO', 'DOUT', 'OPI', 'DTR', 'STR'],
        default='QIO',
        type=str,
        action='store'
    )

    esp_args, extra_args = esp_argParser.parse_known_args(extra_args)

    onboard_mem_speed = esp_args.onboard_mem_speed
    flash_mode = esp_args.flash_mode
    oct_flash = esp_args.oct_flash
    disable_OTG = not esp_args.usb_otg
    board_variant = esp_args.board_variant

    return extra_args


def esp32_s2_args(extra_args):
    global disable_OTG

    esp_argParser = ArgumentParser(prefix_chars='-')
    esp_argParser.add_argument(
        '--usb-otg',
        dest='usb_otg',
        default=False,
        action='store_true'
    )

    esp_args, extra_args = esp_argParser.parse_known_args(extra_args)
    disable_OTG = not esp_args.usb_otg

    return extra_args


def esp32_args(extra_args):
    global board_variant
    global ota
    global flash_mode

    flash_mode = 'DIO'

    esp_argParser = ArgumentParser(prefix_chars='B')
    esp_argParser.add_argument(
        'BOARD_VARIANT',
        dest='board_variant',
        default='',
        action='store'
    )

    esp_args, extra_args = esp_argParser.parse_known_args(extra_args)
    board_variant = esp_args.board_variant

    if board_variant == 'OTA':
        board_variant = ''
        ota = True

    elif board_variant == 'D2WD':
        raise RuntimeError(
            'board variant not supported, Not enough flash capacity'
        )

    return extra_args


def parse_args(extra_args, lv_cflags, brd):
    global board

    if brd is None:
        brd = 'ESP32_GENERIC'

    board = brd

    extra_args = common_args(extra_args)

    if board == 'ESP32_GENERIC':
        extra_args = esp32_args(extra_args)
    elif board == 'ESP32_GENERIC_S2':
        extra_args = esp32_s2_args(extra_args)
    elif board == 'ESP32_GENERIC_S3':
        extra_args = esp32_s3_args(extra_args)

    if lv_cflags:
        lv_cflags += ' -DLV_KCONFIG_IGNORE=1'
    else:
        lv_cflags = '-DLV_KCONFIG_IGNORE=1'

    return extra_args, lv_cflags, board


mpy_cross_cmd = ['make', '-C', 'lib/micropython/mpy-cross']
esp_cmd = [
    'make',
    '',
    f'-j {os.cpu_count()}',
    '-C',
    f'lib/micropython/ports/esp32'
]
clean_cmd = []
compile_cmd = []
submodules_cmd = []
SCRIPT_DIR = ''


def build_commands(_, extra_args, script_dir, lv_cflags, ___):
    global SCRIPT_DIR
    SCRIPT_DIR = script_dir

    clean_cmd.extend(esp_cmd[:])
    clean_cmd[1] = 'clean'
    clean_cmd.append(f'BOARD={board}')

    submodules_cmd.extend(esp_cmd[:])
    submodules_cmd[1] = 'submodules'
    submodules_cmd.append(f'BOARD={board}')

    esp_cmd.extend([
        'SECOND_BUILD=0',
        f'LV_CFLAGS="{lv_cflags}"',
        f'LV_PORT=esp32',
        f'BOARD={board}',
        'USER_C_MODULES=../../../../../ext_mod/micropython.cmake'
    ])

    esp_cmd.extend(extra_args)

    compile_cmd.extend(esp_cmd[:])
    compile_cmd.pop(1)

    if board_variant:
        clean_cmd.append(f'BOARD_VARIANT={board_variant}')
        compile_cmd.insert(7, f'BOARD_VARIANT={board_variant}')
        submodules_cmd.append(f'BOARD_VARIANT={board_variant}')


def get_idf_path():
    if 'IDF_PATH' in os.environ:
        idf_path = os.environ['IDF_PATH']
        if not os.path.exists(idf_path):
            idf_path = None
    else:
        idf_path = None

    return idf_path


cached_idf_version = None


def has_correct_idf():
    global cached_idf_version

    idf_path = get_idf_path()

    if cached_idf_version is None and idf_path:
        exit_code, data = spawn(
            ['python3', f'{idf_path}/tools/idf.py', '--version'],
            out_to_screen=False
        )
        if not exit_code:
            version = data.split('v')[-1].split('-')[0]
            if version:
                cached_idf_version = version

    return (
        cached_idf_version is not None and cached_idf_version == IDF_VER
    )


def build_manifest(
    target, script_dir, lvgl_api, displays, indevs, frozen_manifest
):
    update_mphalport(target)

    with open(f'lib/micropython/ports/esp32/boards/sdkconfig.base', 'r') as f:
        sdkconfig_base = f.read()

    if 'CONFIG_FREERTOS_INTERRUPT_BACKTRACE=n' not in sdkconfig_base:
        sdkconfig_base += '\nCONFIG_FREERTOS_INTERRUPT_BACKTRACE=n\n'
        sdkconfig_base += 'CONFIG_FREERTOS_IDLE_TASK_STACKSIZE=4096\n'

        with open(
            f'lib/micropython/ports/esp32/boards/sdkconfig.base', 'w'
        ) as f:
            f.write(sdkconfig_base)

    manifest_path = 'lib/micropython/ports/esp32/boards/manifest.py'

    generate_manifest(
        script_dir, lvgl_api, manifest_path,
        displays, indevs, frozen_manifest, 'esp32/touch_cal_data.py'
    )


def clean(clean_mpy_cross):
    env, cmds = setup_idf_environ()

    if clean_mpy_cross:
        cross_clean = mpy_cross_cmd[:]
        cross_clean.insert(1, 'clean')
        cross_clean = cmds[:] + [cross_clean]
        spawn(cross_clean, env=env)

    cmds.append(clean_cmd)

    spawn(cmds, env=env)


def get_clean_environment():
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith('IDF')
    }
    if 'PATH' in env:
        env['PATH'] = os.pathsep.join(
            item for item in env['PATH'].split(os.pathsep)
            if 'espressif' not in item and 'esp-idf' not in item
        )

    return env


def environ_helper(idf_path):
    env = get_clean_environment()

    py_path = os.path.split(sys.executable)[0]
    idf_path = os.path.abspath(idf_path)
    idf_tools_path = os.path.join(idf_path, 'tools')

    env['PATH'] = (
        py_path + os.pathsep +
        os.pathsep + idf_tools_path +
        os.pathsep + env.get('PATH', '')
    )
    env['IDF_PATH'] = idf_path

    for key, value in env.items():
        os.environ[key] = value

    if 'GITHUB_RUN_ID' in os.environ:
        if sys.platform.startswith('win'):
            env_cmds = [
                ['echo', f"{py_path}", '|', 'Out-File',
                 '-Append', '-FilePath', '$env:GITHUB_PATH',
                 '-Encoding', 'utf8'],
                ['echo', f"{idf_path}", '|', 'Out-File',
                 '-Append', '-FilePath', '$env:GITHUB_PATH',
                 '-Encoding', 'utf8'],
                ['echo', f"{idf_tools_path}", '|', 'Out-File',
                 '-Append', '-FilePath', '$env:GITHUB_PATH',
                 '-Encoding', 'utf8']
            ]
        else:
            env_cmds = [
                ['echo', f"{py_path}", '>>', '$GITHUB_PATH'],
                ['echo', f"{idf_path}", '>>', '$GITHUB_PATH'],
                ['echo', f"{idf_tools_path}", '>>', '$GITHUB_PATH']
            ]

        spawn(env_cmds, out_to_screen=False)

    return env


IDF_ENVIRON_SET = False


def setup_idf_environ():
    global IDF_ENVIRON_SET
    # There were some modifications made with how the environment gets set up
    # @cheops put quite a bit of time in to research the best solution
    # and also with the testing of the code.
    if IDF_ENVIRON_SET or (not IDF_ENVIRON_SET and has_correct_idf()):
        env = os.environ
        IDF_ENVIRON_SET = True
    elif not IDF_ENVIRON_SET:
        print('Getting ESP-IDF build Environment')
        idf_path = 'lib/esp-idf'

        if not os.path.exists(os.path.join(idf_path, 'export.sh')):
            args = sys.argv[:]

            if 'submodules' not in args:
                args.insert(2, 'submodules')

            args = " ".join(args)

            sys.stderr.write(
                f'ESP-IDF version {IDF_VER} is needed to compile\n'
            )
            sys.stderr.write(
                'Please rerun the build using the command below...\n'
            )
            sys.stderr.write(f'"{sys.executable} {args}"\n\n')
            sys.stderr.flush()
            sys.exit(-1)

        environ_helper(idf_path)

        if 'GITHUB_RUN_ID' in os.environ:
            cmds = [
                [f'export "IDF_PATH={idf_path}"'],
                ['cd', idf_path],
                ['. ./export.sh'],
                ['printenv']
            ]
        else:
            cmds = [
                [f'cd {idf_path}'],
                [f'. ./export.sh'],
                ['printenv']
            ]

        result, output = spawn(cmds, out_to_screen=False)

        if result != 0:
            sys.stderr.write('********* ERROR **********\n')
            sys.stderr.flush()
            print(output)
            sys.exit(result)

        output = [line for line in output.split('\n') if '=' in line]

        temp_env = {
            line.split('=', 1)[0]: line.split('=', 1)[1]
            for line in output
        }

        for key, value in temp_env.items():
            os.environ[key] = value

        env = os.environ
        IDF_ENVIRON_SET = True
    else:
        # this is a sanity check and should never actually run
        env = os.environ

    if 'GITHUB_RUN_ID' in os.environ:
        idf_path = os.path.abspath(env["IDF_PATH"])
        cmds = [
            [f'export "IDF_PATH={idf_path}"'],
            ['cd', f'{idf_path}'],
            ['. ./export.sh'],
            [f'cd {SCRIPT_DIR}']
        ]
    else:
        cmds = []

    return env, cmds


def submodules():
    if has_correct_idf():
        idf_path = os.environ['IDF_PATH']
    else:
        idf_path = 'lib/esp-idf'
        if not os.path.exists(os.path.join(idf_path, 'export.sh')):
            get_espidf()

    cmds = [
        [f'export "IDF_PATH={os.path.abspath(idf_path)}"'],
        ['cd', idf_path],
        ['./install.sh', 'all']
    ]

    print(f'setting up ESP-IDF v{IDF_VER}')
    print('this might take a while...')
    env = {k: v for k, v in os.environ.items()}
    env['IDF_PATH'] = os.path.abspath(idf_path)

    result, _ = spawn(cmds, env=env)
    if result != 0:
        sys.exit(result)

    env, cmds = setup_idf_environ()
    cmds.append(submodules_cmd)

    return_code, _ = spawn(cmds, env=env)
    if return_code != 0:
        sys.exit(return_code)


def compile():  # NOQA
    global PORT
    global flash_size

    env, cmds = setup_idf_environ()

    if ccache:
        env['IDF_CCACHE_ENABLE'] = '1'

    base_config = [
        'CONFIG_ESPTOOLPY_FLASH_SAMPLE_MODE_STR=n',
        'CONFIG_ESPTOOLPY_FLASH_SAMPLE_MODE_DTR=n',
        'CONFIG_ESPTOOLPY_FLASHFREQ_120M=n',
        'CONFIG_ESPTOOLPY_FLASHFREQ_80M=n',
        'CONFIG_SPIRAM_MODE_OCT=n',
        'CONFIG_SPIRAM_MODE_QUAD=n',
        'CONFIG_SPIRAM_SPEED_120M=n',
        'CONFIG_SPIRAM_SPEED_80M=n',
        'CONFIG_ESPTOOLPY_FLASHMODE_QIO=n',
        'CONFIG_ESPTOOLPY_AFTER_NORESET=y',
        'CONFIG_PARTITION_TABLE_CUSTOM=y',
        'CONFIG_ESPTOOLPY_FLASHSIZE_2MB=n',
        'CONFIG_ESPTOOLPY_FLASHSIZE_4MB=n',
        'CONFIG_ESPTOOLPY_FLASHSIZE_8MB=n',
        'CONFIG_ESPTOOLPY_FLASHSIZE_16MB=n',
        'CONFIG_ESPTOOLPY_FLASHSIZE_32MB=n',
        'CONFIG_ESPTOOLPY_FLASHSIZE_64MB=n',
        'CONFIG_ESPTOOLPY_FLASHSIZE_128MB=n',
        'CONFIG_COMPILER_OPTIMIZATION_SIZE=n',
        'CONFIG_COMPILER_OPTIMIZATION_PERF=n',
        'CONFIG_COMPILER_OPTIMIZATION_CHECKS_SILENT=y'
    ]

    if DEBUG:
        base_config.extend([
            'CONFIG_BOOTLOADER_LOG_LEVEL_NONE=n',
            'CONFIG_BOOTLOADER_LOG_LEVEL_ERROR=n',
            'CONFIG_BOOTLOADER_LOG_LEVEL_WARN=n',
            'CONFIG_BOOTLOADER_LOG_LEVEL_INFO=n',
            'CONFIG_BOOTLOADER_LOG_LEVEL_DEBUG=y',
            'CONFIG_BOOTLOADER_LOG_LEVEL_VERBOSE=n',
            'CONFIG_LCD_ENABLE_DEBUG_LOG=y',
            'CONFIG_HAL_LOG_LEVEL_NONE=n',
            'CONFIG_HAL_LOG_LEVEL_ERROR=n',
            'CONFIG_HAL_LOG_LEVEL_WARN=n',
            'CONFIG_HAL_LOG_LEVEL_INFO=n',
            'CONFIG_HAL_LOG_LEVEL_DEBUG=y',
            'CONFIG_HAL_LOG_LEVEL_VERBOSE=n',
            'CONFIG_LOG_MAXIMUM_LEVEL_ERROR=n',
            'CONFIG_LOG_MAXIMUM_LEVEL_WARN=n',
            'CONFIG_LOG_MAXIMUM_LEVEL_INFO=n',
            'CONFIG_LOG_MAXIMUM_LEVEL_DEBUG=y',
            'CONFIG_LOG_MAXIMUM_LEVEL_VERBOSE=n',
            'CONFIG_LOG_DEFAULT_LEVEL_NONE=n',
            'CONFIG_LOG_DEFAULT_LEVEL_ERROR=n',
            'CONFIG_LOG_DEFAULT_LEVEL_WARN=n',
            'CONFIG_LOG_DEFAULT_LEVEL_INFO=n',
            'CONFIG_LOG_DEFAULT_LEVEL_DEBUG=y',
            'CONFIG_LOG_DEFAULT_LEVEL_VERBOSE=n',
        ])

    base_config.append('')

    base_config.append(f'CONFIG_ESPTOOLPY_FLASHSIZE_{flash_size}MB=y')
    base_config.append(''.join([
        'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME=',
        f'"{SCRIPT_DIR}/build/partitions.csv"'
    ]))

    if optimize_size:
        base_config.append('CONFIG_COMPILER_OPTIMIZATION_SIZE=y')
    else:
        base_config.append('CONFIG_COMPILER_OPTIMIZATION_PERF=y')

    if onboard_mem_speed == 120 or flash_mode in ('DTR', 'STR'):
        base_config.append('CONFIG_IDF_EXPERIMENTAL_FEATURES=y')

    base_config.append(f'CONFIG_ESPTOOLPY_FLASHFREQ_{onboard_mem_speed}M=y')
    base_config.append('CONFIG_SPIRAM_SPEED_{onboard_mem_speed}M=y')

    if oct_flash:
        base_config.append('CONFIG_ESPTOOLPY_OCT_FLASH=y')

    if board_variant:
        if board_variant == 'SPIRAM':
            base_config.append('CONFIG_SPIRAM_MODE_QUAD=y')
        elif board_variant == 'SPIRAM_OCT':
            base_config.append('CONFIG_SPIRAM_MODE_OCT=y')

    if flash_mode == 'STR':
        base_config.append('CONFIG_ESPTOOLPY_FLASH_SAMPLE_MODE_STR=y')
    elif flash_mode == 'DTR':
        base_config.append('CONFIG_ESPTOOLPY_FLASH_SAMPLE_MODE_DTR=y')
    else:
        base_config.append(f'CONFIG_ESPTOOLPY_FLASHMODE_{flash_mode}=y')

    mpconfigboard_cmake_path = (
        'lib/micropython/ports/esp32/boards/'
        f'{board}/mpconfigboard.cmake'
    )

    with open(mpconfigboard_cmake_path, 'rb') as f:
        data = f.read().decode('utf-8')

    sdkconfig = (
        'set(SDKCONFIG_DEFAULTS ${SDKCONFIG_DEFAULTS} '
        '../../../../build/sdkconfig.board)'
    )

    if partition_size == -1:
        p_size = 0x267000
    else:
        p_size = partition_size

    partition = Partition(p_size)
    partition.save()

    if sdkconfig not in data:
        data += '\n' + sdkconfig + '\n'

        with open(mpconfigboard_cmake_path, 'wb') as f:
            f.write(data.encode('utf-8'))

    board_config_path = f'build/sdkconfig.board'
    with open(board_config_path, 'w') as f:
        f.write('\n'.join(base_config))

    if board in ('ESP32_GENERIC_S2', 'ESP32_GENERIC_S3') and disable_OTG:
        mphalport_path = 'lib/micropython/ports/esp32/mphalport.c'

        with open(mphalport_path, 'rb') as f:
            data = f.read().decode('utf-8')

        data = data.replace(
            '#elif CONFIG_USB_OTG_SUPPORTED',
            '#elif MP_USB_OTG'
        )

        with open(mphalport_path, 'wb') as f:
            f.write(data.encode('utf-8'))

        main_path = 'lib/micropython/ports/esp32/main.c'

        with open(main_path, 'rb') as f:
            data = f.read().decode('utf-8')

        data = data.replace(
            '#elif CONFIG_USB_OTG_SUPPORTED',
            '#elif MP_USB_OTG'
        )

        with open(main_path, 'wb') as f:
            f.write(data.encode('utf-8'))

        mpconfigboard_path = (
            f'lib/micropython/ports/esp32/boards/{board}/mpconfigboard.h'
        )

        with open(mpconfigboard_path, 'rb') as f:
            data = f.read().decode('utf-8')

        if 'MP_USB_OTG' not in data:
            data += (
                '\n'
                '#ifndef MP_USB_OTG\n'
                '#define MP_USB_OTG    (0)\n'
                '#endif'
            )

            with open(mpconfigboard_path, 'wb') as f:
                f.write(data.encode('utf-8'))

    src_path = 'micropy_updates/esp32'
    dst_path = 'lib/micropython/ports/esp32'

    for file in os.listdir(src_path):
        src_file = os.path.join(src_path, file)
        dst_file = os.path.join(dst_path, file)
        shutil.copyfile(src_file, dst_file)

    cmds = compile_cmd

    ret_code, output = spawn(cmds, env=env, cmpl=True)
    if ret_code != 0:
        if (
            'partition is too small ' not in output or
            skip_partition_resize
        ):
            sys.exit(ret_code)

        if partition_size != -1:
            sys.exit(ret_code)

        sys.stdout.write('\n\033[31;1m***** Resizing Partition *****\033[0m\n')
        sys.stdout.flush()

        end = output.split('(overflow ', 1)[-1]
        overflow_amount = int(end.split(')', 1)[0], 16)

        partition.set_app_size(overflow_amount)
        partition.save()

        sys.stdout.write(
            '\n\033[31;1m***** Running build again *****\033[0m\n\n'
        )
        sys.stdout.flush()

        compile_cmd[4] = 'SECOND_BUILD=1'
        ret_code, output = spawn(cmds, env=env, cmpl=True)

        if ret_code != 0:
            sys.exit(ret_code)

    elif not skip_partition_resize:
        if partition_size == -1 and 'build complete' in output:
            app_size = output.rsplit('micropython.bin binary size ')[-1]
            app_size = int(
                app_size.split(' bytes')[0].strip(),
                16
            )

            remaining = app_size - partition.get_app_size()

            if remaining > 0x1000:
                sys.stdout.write(
                    '\n\033[31;1m***** Resizing Partition *****\033[0m\n'
                )
                sys.stdout.flush()

                partition.set_app_size(-remaining)
                partition.save()

                sys.stdout.write(
                    '\n\033[31;1m***** Running build again *****\033[0m\n\n'
                )
                sys.stdout.flush()

                compile_cmd[4] = 'SECOND_BUILD=1'

                ret_code, output = spawn(cmds, env=env, cmpl=True)

                if ret_code != 0:
                    sys.exit(ret_code)

    if 'To flash, run:' in output:
        output = output.rsplit('To flash, run:')[-1].strip()

        espressif_path = os.path.expanduser('~/.espressif')

        for ver in ('3.8', '3.9', '3.10', '3.11', '3.12'):
            python_path = (
                f'{espressif_path}/python_env/idf{IDF_VER[:-2]}_py{ver}_env/bin'
            )
            if os.path.exists(python_path):
                break
        else:
            raise RuntimeError(
                'unable to locate pyton version used in the ESP-IDF'
            )

        python_path += '/python'

        output = output.split('python ', 1)[-1]
        output = output.split('\n', 1)[0]

        build_name = f'build-{board}'

        if board_variant:
            build_name += f'-{board_variant}'

        full_file_path = (
            f'{SCRIPT_DIR}/lib/micropython/ports/esp32/{build_name}'
        )
        bin_files = []
        for item in output.split('0x')[1:]:
            item, bf = item.split(build_name, 1)
            bf = f'"{full_file_path}{bf.strip()}"'
            bin_files.append(f'0x{item.strip()} {bf}')

        bin_files = ' '.join(bin_files)

        old_bin_files = ['0x' + item.strip() for item in output.split('0x')[1:]]
        old_bin_files = ' '.join(old_bin_files)

        os.remove('build/lvgl_header.h')

        for f in os.listdir('build'):
            if f.startswith('lvgl'):
                continue

            os.remove(os.path.join('build', f))

        if board_variant:
            build_name += f'-{board_variant}'

        build_bin_file = f'build/lvgl_micropy_{build_name[6:]}-{flash_size}'
        if oct_flash:
            build_bin_file += '_OCTFLASH'

        build_bin_file += '.bin'
        build_bin_file = f'"{os.path.abspath(build_bin_file)}"'

        chip = output.split('--chip ', 1)[-1].split(' ', 1)[0]

        cmds = [''.join([
            f'{python_path} -m esptool --chip {chip} ',
            f'merge_bin -o {build_bin_file} {bin_files}'
        ])]

        result, _ = spawn(cmds, env=env)
        if result:
            sys.exit(result)

        output = output.replace(old_bin_files, f'0x0 {build_bin_file}')
        output = python_path + ' ' + output

        if deploy:
            result, tool_path = spawn(
                [[
                    python_path,
                    '-c "import esptool;print(esptool.__file__);"'
                ]],
                out_to_screen=False
            )

            if result != 0:
                raise RuntimeError('ERROR collecting esptool path')

            tool_path = os.path.split(os.path.split(tool_path.strip())[0])
            sys.path.insert(0, tool_path)

            from esptool.targets import CHIP_DEFS  # NOQA
            from esptool.util import FatalError  # NOQA
            from serial.tools import list_ports  # NOQA

            cmd = output.replace('-b 460800', f'-b {BAUD}')

            def get_port_list():
                pts = sorted(p.device for p in list_ports.comports())
                if sys.platform.startswith('linux'):
                    serial_path = '/dev/serial/by_id'
                    if os.path.exists(serial_path):
                        pts_alt = [
                            os.path.join(serial_path, fle)
                            for fle in os.listdir(serial_path)
                        ]
                        pts = pts_alt + pts

                return pts

            def find_esp32(chip):
                found_ports = []
                for prt in get_port_list():
                    chip_class = CHIP_DEFS[chip]
                    try:
                        _esp = chip_class(prt, 115200, False)
                    except (FatalError, OSError):
                        continue

                    try:
                        _esp.connect('no_reset', 2)
                    except (FatalError, OSError):
                        pass
                    else:
                        found_ports.append(port)

                    if _esp and _esp._port:  # NOQA
                        _esp._port.close()  # NOQA

                return found_ports

            if PORT is None:
                ports = find_esp32(
                    cmd.split(
                        '--chip ', 1
                    )[-1].split(
                        ' ', 1
                    )[0]
                )
                if len(ports) > 1:
                    query = []
                    for i, port in enumerate(ports):
                        query.append(str(i + 1) + ': ' + port)
                    query.append('')
                    query.append('Which ESP32? :')

                    res = input('\n'.join(query))
                    res = int(res) - 1
                else:
                    res = 0

                PORT = ports[res]

            cmd = cmd.replace('-p (PORT)', f'-p {PORT}')

            erase_flash = (
                f'{python_path} -m esptool '
                f'-p {PORT} -b 460800 erase_flash'
            )

            result, _ = spawn(erase_flash)
            if result != 0:
                sys.exit(result)

            result, _ = spawn(cmd)

        else:
            erase_cmd = ''.join([
                f'{python_path} -m esptool ',
                f'-p (PORT) -b 460800 erase_flash'
            ])

            print()
            print()
            print('To flash firmware:')
            print('Replace "(PORT)" with the serial port for your esp32')
            print('and run the commands.')
            print()
            print(erase_cmd)
            print()
            print(output.replace('-b 460800', '-b 921600'))
            print()


def mpy_cross():
    return_code, _ = spawn(mpy_cross_cmd, cmpl=True)
    if return_code != 0:
        sys.exit(return_code)
