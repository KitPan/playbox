import theano.tensor as t
from net import Net
from contiguousLayer import ContiguousLayer
from convolutionalLayer import ConvolutionalLayer
import datasetUtils, numpy, os

'''
'''
if __name__ == '__main__' :
    import argparse, logging
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', dest='logfile', default=None,
                        help='Specify log output file.')
    parser.add_argument('--level', dest='level', default='INFO',
                        help='Log Level.')
    parser.add_argument('--learnC', dest='learnC', default=.0031,
                        help='Rate of learning on Convolutional Layers.')
    parser.add_argument('--learnF', dest='learnF', default=.0015,
                        help='Rate of learning on Fully-Connected Layers.')
    parser.add_argument('--momentum', dest='momentum', default=.3,
                        help='Momentum rate all layers.')
    parser.add_argument('--kernel', dest='kernel', default=6,
                        help='Number of Convolutional Kernels in each Layer.')
    parser.add_argument('--neuron', dest='neuron', default=120,
                        help='Number of Neurons in Hidden Layer.')
    parser.add_argument('--limit', dest='limit', default=5,
                        help='Number of runs between validation checks')
    parser.add_argument('--stop', dest='stop', default=5,
                        help='Number of inferior validation checks before ending')
    parser.add_argument('--base', dest='base', default='leNet5',
                        help='Base name of the network output file.')
    parser.add_argument('--syn', dest='synapse', default=None,
                        help='Load from a previously saved network.')
    parser.add_argument('data', help='Pickle file for the training and test sets')
    options = parser.parse_args()

    # this makes the indexing more intuitive
    DATA, LABEL = 0, 1

    # setup the logger
    log = logging.getLogger('cnnTrainer: ' + options.data)
    log.setLevel(options.level.upper())
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    stream = logging.StreamHandler()
    stream.setLevel(options.level.upper())
    stream.setFormatter(formatter)
    log.addHandler(stream)
    if options.logfile is not None :
        logFile = logging.FileHandler(options.logfile)
        logFile.setLevel(options.level.upper())
        logFile.setFormatter(formatter)
        log.addHandler(logFile)

    # create a random number generator for efficiency
    from numpy.random import RandomState
    from time import time
    from operator import mul
    rng = RandomState(int(time()))

    input = t.ftensor4('input')
    expectedOutput = t.bvector('expectedOutput')

    log.info('Ingesting Imagery...')
    train, test, labels = datasetUtils.ingestImagery(
        datasetUtils.pickleDataset(options.data, log=log), log=log)

    # create the network -- LeNet-5
    network = Net(regType='', log=log)

    if options.synapse is not None :
        # load a previously saved network
        log.info('Loading Network...')
        network.load(options.synapse)
    else :
        log.info('Initializing Network...')

        # add convolutional layers
        network.addLayer(ConvolutionalLayer(
            layerID='c1', input=input, inputSize=(1,1,28,28), kernelSize=(6,1,5,5),
            downsampleFactor=(2,2), randomNumGen=rng, learningRate=options.learnC))
        # refactor the output to be (numImages*numKernels, 1, numRows, numCols)
        # this way we don't combine the channels kernels we created in the first
        # layer and destroy our dimensionality
        netOutputSize = network.getNetworkOutputSize()
        netOutputSize = (netOutputSize[0] * netOutputSize[1], 1,
                         netOutputSize[2], netOutputSize[3])
        network.addLayer(ConvolutionalLayer(
            layerID='c2', input=network.getNetworkOutput().reshape(netOutputSize),
            inputSize=netOutputSize, kernelSize=(6,1,5,5), downsampleFactor=(2,2), 
            randomNumGen=rng, learningRate=options.learnC))

        # add fully connected layers
        network.addLayer(ContiguousLayer(
            layerID='f3', input=network.getNetworkOutput().flatten(),
            inputSize=reduce(mul, network.getNetworkOutputSize()),
            numNeurons=int(options.neuron), learningRate=float(options.learnF),
            randomNumGen=rng))
        network.addLayer(ContiguousLayer(
            layerID='f4', input=network.getNetworkOutput(),
            inputSize=network.getNetworkOutputSize(), numNeurons=len(labels),
            learningRate=float(options.learnF), randomNumGen=rng))

    train = [(datasetUtils.readImage('G:/coding/input/binary_smaller/0/0.tif', log), 0)]
    train = datasetUtils.makeMiniBatch(train)

    globalCount = lastBest = degradationCount = 0
    runningAccuracy = 0.0
    lastSave = ''

    expBuffer = numpy.zeros(len(labels), dtype='int32')
    expBuffer[train[LABEL]] = 1
    
    from time import time
    numRuns = 10000

    # test the classify runtime
    print "Classifying Inputs..."
    timer = time()
    for ii in range(numRuns) :
        out = network.classify(train[DATA])
    timer = time() - timer
    print "total time: " + str(timer) + \
          "s | per input: " + str(timer/numRuns) + "s"
    print (out.argmax(), out)
 
    print "Training Network..."
    timer = time()
    for i in range(numRuns) :
        network.train(train[DATA], expBuffer)
    timer = time() - timer
    print "total time: " + str(timer) + \
          "s | per input: " + str(timer/numRuns) + "s"
    out = network.classify(train[DATA])
    print (out.argmax(), out)

    lastSave = options.base + \
               '_learnC' + str(options.learnC) + \
               '_learnF' + str(options.learnF) + \
               '_momentum' + str(options.momentum) + \
               '_kernel' + str(options.kernel) + \
               '_neuron' + str(options.neuron) + \
               '_epoch' + str(lastBest) + '.pkl.gz'
    log.info('Saving to: ' + os.path.abspath(lastSave))
    network.save(os.path.abspath(lastSave))

'''
    while True :

        # run the specified number of epochs
        numEpochs = int(options.limit)
        for localEpoch in range(numEpochs) :
            
            for ii in range(len(train[DATA])) :
                expBuffer[train[LABEL]] = 1
                network.train(train[DATA], expBuffer)
                expBuffer[train[LABEL]] = 0

        # calculate the accuracy against the test set
        curAcc = 0.0
        for input, label in zip(test[DATA], test[LABEL]) :
            if network.classify(input.get_value()).argmax() == label.get_value() :
                curAcc += 1.0
        curAcc /= float(len(test[LABEL]))

        # check if we've done better
        if curAcc > runningAccuracy :
            # reset and save the network
            degradationCount = 0
            runningAccuracy = curAcc
            lastBest = globalCount
            lastSave = options.base + \
                       '_learnC' + str(options.learnC) + \
                       '_learnF' + str(options.learnF) + \
                       '_momentum' + str(options.momentum) + \
                       '_kernel' + str(options.kernel) + \
                       '_neuron' + str(options.neuron) + \
                       '_epoch' + str(lastBest) + '.tar.gz'
            network.save(lastSave)
        else :
            # quit once we've had 'stop' times of less accuracy
            degradationCount += 1
            if degradationCount > options.stop :
                break
        globalCount += numEpochs

    # rename the network which achieved the highest accuracy
    os.rename(lastBest,
              options.base + '_FinalOnHoldOut_' + \
              options.data + '_epoch' + str(lastBest) + \
              '_acc' + str(runningAccuracy) + '.tar.gz')
'''