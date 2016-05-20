import theano.tensor as t
from ae.net import StackedAENetwork
from ae.contiguousAE import ContractiveAutoEncoder
from ae.convolutionalAE import ConvolutionalAutoEncoder
from dataset.ingest.labeled import ingestImagery
from dataset.shared import splitToShared
from nn.contiguousLayer import ContiguousLayer
from trainNetwork import trainUnsupervised, trainSupervised
from nn.net import TrainerNetwork
import argparse, logging
from time import time

if __name__ == '__main__' :
    '''This application runs semi-supervised training on a given dataset. The
       utimate goal is to setup the early layers of the Neural Network to
       identify pattern in the data unsupervised learning. Here we used a 
       Stacked Autoencoder (SAE) and greedy training.
       We then translate the SAE to a Neural Network (NN) and add a 
       classification layer. From there we use supervised training to fine-tune
       the weights to classify objects we select as important.
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', dest='logfile', type=str, default=None,
                        help='Specify log output file.')
    parser.add_argument('--level', dest='level', default='INFO', type=str, 
                        help='Log Level.')
    parser.add_argument('--learnC', dest='learnC', type=float, default=.0031,
                        help='Rate of learning on Convolutional Layers.')
    parser.add_argument('--learnF', dest='learnF', type=float, default=.0015,
                        help='Rate of learning on Fully-Connected Layers.')
    parser.add_argument('--contrF', dest='contrF', type=float, default=None,
                        help='Rate of contraction of the latent space on ' +
                             'Fully-Connected Layers.')
    parser.add_argument('--momentum', dest='momentum', type=float, default=.3,
                        help='Momentum rate all layers.')
    parser.add_argument('--dropout', dest='dropout', type=bool, default=False,
                        help='Enable dropout throughout the network. Dropout '\
                             'percentages are based on optimal reported '\
                             'results. NOTE: Networks using dropout need to '\
                             'increase both neural breadth and learning rates')
    parser.add_argument('--kernel', dest='kernel', type=int, default=6,
                        help='Number of Convolutional Kernels in each Layer.')
    parser.add_argument('--neuron', dest='neuron', type=int, default=120,
                        help='Number of Neurons in Hidden Layer.')
    parser.add_argument('--epoch', dest='numEpochs', type=int, default=15,
                        help='Number of epochs to run per layer during ' +
                             'unsupervised pre-training.')
    parser.add_argument('--limit', dest='limit', type=int, default=5,
                        help='Number of runs between validation checks ' +
                             'during supervised learning.')
    parser.add_argument('--stop', dest='stop', type=int, default=5,
                        help='Number of inferior validation checks to end ' +
                             'the supervised learning session.')
    parser.add_argument('--holdout', dest='holdout', type=float, default=.05,
                        help='Percent of data to be held out for testing.')
    parser.add_argument('--batch', dest='batchSize', type=int, default=5,
                        help='Batch size for training and test sets.')
    parser.add_argument('--base', dest='base', type=str, default='./leNet5',
                        help='Base name of the network output and temp files.')
    parser.add_argument('--syn', dest='synapse', type=str, default=None,
                        help='Load from a previously saved network.')
    parser.add_argument('data', help='Directory or pkl.gz file for the ' +
                                     'training and test sets')
    options = parser.parse_args()

    # setup the logger
    log = logging.getLogger('semiSupervisedTrainer: ' + options.data)
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
    from operator import mul
    rng = RandomState(int(time()))

    # NOTE: The pickleDataset will silently use previously created pickles if
    #       one exists (for efficiency). So watch out for stale pickles!
    train, test, labels = ingestImagery(filepath=options.data, shared=False,
                                        batchSize=options.batchSize, 
                                        holdoutPercentage=options.holdout, 
                                        log=log)
    trainShape = train[0].shape

    # create the stacked network -- LeNet-5 (minus the output layer)
    network = StackedAENetwork(splitToShared(train, borrow=True), log=log)

    if options.synapse is not None :
        # load a previously saved network
        network.load(options.synapse)
    else :
        log.info('Initializing Network...')
        input = t.ftensor4('input')

        # add convolutional layers
        network.addLayer(ConvolutionalAutoEncoder(
            layerID='c1', input=input, 
            inputSize=trainShape[1:], 
            kernelSize=(options.kernel,trainShape[2],5,5),
            downsampleFactor=(2,2), randomNumGen=rng,
            dropout=.8 if options.dropout else 1.,
            learningRate=options.learnC))

        # refactor the output to be (numImages*numKernels,1,numRows,numCols)
        # this way we don't combine the channels kernels we created in 
        # the first layer and destroy our dimensionality
        network.addLayer(ConvolutionalAutoEncoder(
            layerID='c2',
            input=network.getNetworkOutput(), 
            inputSize=network.getNetworkOutputSize(), 
            kernelSize=(options.kernel,options.kernel,5,5),
            downsampleFactor=(2,2), randomNumGen=rng,
            dropout=.5 if options.dropout else 1.,
            learningRate=options.learnC))

        # add fully connected layers
        network.addLayer(ContractiveAutoEncoder(
            layerID='f3', input=network.getNetworkOutput(),
            inputSize=(network.getNetworkOutputSize()[0], 
                       reduce(mul, network.getNetworkOutputSize()[1:])),
            numNeurons=options.neuron, learningRate=options.learnF,
            dropout=.5 if options.dropout else 1.,
            randomNumGen=rng))

        # the final output layer is removed from the normal NN --
        # the output layer is special, as it makes decisions about
        # patterns identified in previous layers, so it should only
        # be influenced/trained during supervised learning. 

    # train the SAE for unsupervised pattern recognition
    bestNetwork = trainUnsupervised(network, __file__, options.data, 
                                    numEpochs=options.limit, stop=options.stop, 
                                    synapse=options.synapse, base=options.base, 
                                    dropout=options.dropout, 
                                    learnC=options.learnC,
                                    learnF=options.learnF, 
                                    contrF=options.contrF, 
                                    momentum=options.momentum, 
                                    kernel=options.kernel, 
                                    neuron=options.neuron, log=log)

    # cleanup the network -- this ensures the profile is written
    del network

    # translate into a neural network --
    # this transfers our unsupervised pre-training into a decent
    # starting condition for our supervised learning
    network = TrainerNetwork(train, splitToShared(test,  borrow=True), labels,
                             filepath=bestNetwork, log=log)

    # add the classification layer
    network.addLayer(ContiguousLayer(
        layerID='f4', input=network.getNetworkOutput(),
        inputSize=network.getNetworkOutputSize(), numNeurons=len(labels),
        learningRate=options.learnF, randomNumGen=rng))

    # train the NN for supervised classification
    trainSupervised(network, __file__, options.data, 
                    numEpochs=options.limit, stop=options.stop, 
                    synapse=options.synapse, base=options.base, 
                    dropout=options.dropout, learnC=options.learnC, 
                    learnF=options.learnF, momentum=options.momentum, 
                    kernel=options.kernel, neuron=options.neuron, log=log)

    # cleanup the network -- this ensures the profile is written
    del network